"""Wakes in Postgres, table `wakes`: a row per house wake and per reminder occurrence, its `kind` saying which."""

from datetime import datetime
from typing import Any, LiteralString

import psycopg
from psycopg.types.json import Jsonb

from ..db.database import Database, DatabaseUnavailable
from .deposit_rule import from_json as rule_from_json
from .deposit_rule import landed_from_json
from .repeat import from_json, to_json
from ..conversations.quiet import QUIET
from .wakes import (MAX_BRIEF, MAX_TOOLS, Delivery, Due, Outcome, Received, Reminder, SaidBefore, Scheduled, Wake, Wakes,
                    WakesUnavailable, WatchWake)

_DUE = ("SELECT id, kind, household_id, event_id, event, who, what, at, person_id, made_by, brief, due_at, repeat, "
        "extract(epoch FROM clock_timestamp() - due_at), landed, route, tools, watch_id, changes, taint, made_conversation_id, made_turn_id FROM wakes WHERE settled_at IS NULL AND trigger = 'time' "
        "AND due_at <= now() ORDER BY due_at, id LIMIT %s")
_REMINDER: LiteralString = (
    "SELECT id, household_id, person_id, made_by, brief, due_at, repeat, deposit_rule, CASE WHEN settled_at IS NULL THEN 'scheduled' "
    "WHEN delivery = 'sending' THEN 'sending' WHEN delivery = 'undelivered' THEN 'undelivered' ELSE 'failed' END, "
    "route, tools, taint, made_conversation_id, made_turn_id FROM wakes ")
_LISTED: LiteralString = (
    "kind = 'reminder' AND dismissed_at IS NULL AND (settled_at IS NULL OR delivery IN ('sending', 'undelivered') "
    "OR outcome IN ('failed', 'no_person'))")
"""A reminder its person still needs to see: still to fire, fired and not delivered, or failed, and not dismissed."""
_SETTLED: LiteralString = (
    "settled_at = now(), outcome = %(outcome)s, "
    "delivery = CASE WHEN kind = 'reminder' AND route = 'phone' AND %(outcome)s = 'turn' THEN 'sending' END")
_SETTLE_AND_NEXT = (
    "WITH s AS (UPDATE wakes SET " + _SETTLED + " WHERE id = %(id)s AND settled_at IS NULL "
    "RETURNING household_id, kind, person_id, made_by, brief, repeat, route, tools, taint, made_conversation_id, "
    "made_turn_id), "
    "n AS (INSERT INTO wakes (household_id, kind, event_id, event, at, due_at, person_id, made_by, brief, repeat, "
    "route, tools, taint, made_conversation_id, made_turn_id) "
    "SELECT household_id, 'reminder', 'reminder:' || gen_random_uuid(), 'reminder', %(next)s, %(next)s, person_id, "
    "made_by, brief, "
    "repeat, route, tools, taint, made_conversation_id, made_turn_id FROM s WHERE kind = 'reminder' AND repeat IS NOT NULL RETURNING id) "
    "SELECT (SELECT count(*) FROM s), (SELECT count(*) FROM n)")

_HERS: LiteralString = (
    "SELECT max(a.at) FROM wakes o "
    "JOIN turns h ON h.household_id = o.household_id AND h.source = 'wake:' || o.id "
    "JOIN turns a ON a.conversation_id = h.conversation_id AND a.answers = h.id AND a.author = 'ashley' "
    "WHERE o.household_id = w.household_id AND o.kind = 'house' AND o.who = w.who AND o.id <> w.id")
_SAID_BEFORE = (
    "SELECT (SELECT max(t.at) FROM turns t WHERE t.household_id = w.household_id AND t.author = 'person' "
    "AND t.speaker_id = %(person)s), "
    "(" + _HERS + " AND o.event = w.event), "
    "(" + _HERS + " AND a.text <> %(quiet)s) "
    "FROM wakes w WHERE w.id = %(wake)s AND w.kind = 'house'")


def _due(r: tuple[Any, ...]) -> Due:
    wake: Wake | Reminder | WatchWake
    if r[1] == "reminder":
        wake = _reminder(r[2], r[8], r[9], r[10], r[11], r[12], r[14], r[15], r[16], r[19], r[20], r[21])
    elif r[1] == "watch":
        wake = WatchWake(int(r[2]), int(r[8]), int(r[17]), "paused" if r[6] == "paused" else "changed", dict(r[18]))
    else:
        wake = Wake(int(r[2]), r[3], r[4], r[5], r[6], r[7])
    return Due(int(r[0]), wake, float(r[13]))


def _reminder(household_id: Any, person_id: Any, made_by: Any, brief: Any, due_at: Any, repeat: Any,
              landed: Any = None, route: Any = "phone", tools: Any = None, taint: Any = None,
              made_conversation: Any = None, made_turn: Any = None) -> Reminder:
    return Reminder(int(household_id), int(person_id), int(made_by), str(brief), due_at,
                    None if repeat is None else from_json(repeat), None if landed is None else landed_from_json(landed),
                    "quiet" if route == "quiet" else "phone", None if tools is None else tuple(str(t) for t in tools),
                    None if taint is None else str(taint),
                    None if made_turn is None else (int(made_conversation), int(made_turn)))


def _made_in(reminder: Reminder) -> tuple[int | None, int | None]:
    return (None, None) if reminder.made_in is None else reminder.made_in


def _checked(reminder: Reminder) -> None:
    if not 1 <= len(reminder.brief) <= MAX_BRIEF or "\x00" in reminder.brief:
        raise ValueError(f"a reminder's brief is 1 to {MAX_BRIEF} characters, without a NUL")
    if reminder.tools is not None and len(reminder.tools) > MAX_TOOLS:
        raise ValueError(f"a reminder has at most {MAX_TOOLS} tools")


def _tools(reminder: Reminder) -> list[str] | None:
    return None if reminder.tools is None else list(reminder.tools)


def _repeat(reminder: Reminder) -> Jsonb | None:
    return None if reminder.repeat is None else Jsonb(to_json(reminder.repeat))


class PostgresWakes(Wakes):
    def __init__(self, database: Database) -> None:
        self._database = database

    async def receive(self, device_id: int, wake: Wake) -> Received:
        stored = await self._one(
            "WITH made AS (INSERT INTO wakes (household_id, device_id, event_id, event, who, what, at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (household_id, event_id) DO NOTHING RETURNING id) "
            "SELECT id, true FROM made UNION ALL "
            "SELECT id, false FROM wakes WHERE household_id = %s AND event_id = %s AND NOT EXISTS (SELECT 1 FROM made)",
            (wake.household_id, device_id, wake.event_id, wake.event, wake.who, wake.what, wake.at,
             wake.household_id, wake.event_id))
        if stored is None:
            # A delivery racing this one stored it after this statement's snapshot began.
            stored = await self._one("SELECT id, false FROM wakes WHERE household_id = %s AND event_id = %s",
                                     (wake.household_id, wake.event_id))
        if stored is None:
            raise WakesUnavailable("the wake was neither stored nor found")
        return Received(int(stored[0]), bool(stored[1]))

    async def schedule(self, reminder: Reminder) -> int:
        _checked(reminder)
        if reminder.landed is not None:
            raise ValueError("a scheduled reminder carries no landed deposit; only Deposits.fire sets one")
        made = await self._one(
            "INSERT INTO wakes (household_id, kind, event_id, event, at, due_at, person_id, made_by, brief, repeat, "
            "route, tools, taint, made_conversation_id, made_turn_id) VALUES (%s, 'reminder', "
            "'reminder:' || gen_random_uuid(), 'reminder', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (reminder.household_id, reminder.due_at, reminder.due_at, reminder.person_id, reminder.made_by,
             reminder.brief, _repeat(reminder), reminder.route, _tools(reminder), reminder.taint,
             *_made_in(reminder)))
        if made is None:
            raise WakesUnavailable("the reminder was not stored")
        return int(made[0])

    async def edit(self, household_id: int, person_id: int, wake_id: int, changed: Reminder) -> bool:
        _checked(changed)
        return await self._count(
            "UPDATE wakes SET brief = %s, route = %s, tools = %s, taint = COALESCE(%s, taint), "
            "made_conversation_id = COALESCE(%s, made_conversation_id), made_turn_id = COALESCE(%s, made_turn_id), "
            "due_at = CASE WHEN trigger = 'event' THEN due_at ELSE %s END, "
            "at = CASE WHEN trigger = 'event' THEN at ELSE %s END, "
            "repeat = CASE WHEN trigger = 'event' THEN NULL ELSE %s::jsonb END "
            "WHERE id = %s AND household_id = %s AND kind = 'reminder' AND settled_at IS NULL "
            "AND (person_id = %s OR made_by = %s)",
            (changed.brief, changed.route, _tools(changed), changed.taint, *_made_in(changed), changed.due_at, changed.due_at, _repeat(changed), wake_id,
             household_id, person_id, person_id)) == 1

    async def due(self, limit: int) -> tuple[Due, ...]:
        return tuple(_due(r) for r in await self._all(_DUE, (limit,)))

    async def settle(self, wake_id: int, outcome: Outcome, next_due: datetime | None = None) -> bool:
        params = {"outcome": outcome, "id": wake_id, "next": next_due}
        if next_due is None:
            return await self._count("UPDATE wakes SET " + _SETTLED + " WHERE id = %(id)s AND settled_at IS NULL",
                                     params) == 1
        counts = await self._one(_SETTLE_AND_NEXT, params)
        return counts is not None and int(counts[0]) == 1

    async def reminders(self, household_id: int, person_id: int) -> tuple[Scheduled, ...]:
        rows = await self._all(_REMINDER + "WHERE household_id = %s AND " + _LISTED + " AND (person_id = %s "
                               "OR made_by = %s) ORDER BY due_at, id", (household_id, person_id, person_id))
        return tuple(Scheduled(int(r[0]), _reminder(*r[1:7], route=r[9], tools=r[10], taint=r[11], made_conversation=r[12],
                                                  made_turn=r[13]), r[8], None if r[7] is None else rule_from_json(r[7]))
                     for r in rows)

    async def refire(self, wake_id: int, after_s: float) -> int:
        got = await self._one("UPDATE wakes SET fire_attempts = fire_attempts + 1, due_at = now() + make_interval("
                              "secs => %s) WHERE id = %s AND settled_at IS NULL RETURNING fire_attempts",
                              (after_s, wake_id))
        return 0 if got is None else int(got[0])

    async def undelivered(self, limit: int, retry_s: float, within_s: float) -> tuple[Delivery, ...]:
        rows = await self._all(
            "SELECT id, household_id, person_id, delivery_attempts FROM wakes WHERE delivery IN ('sending', "
            "'undelivered') AND dismissed_at IS NULL AND settled_at > now() - make_interval(secs => %s) AND (delivery_tried_at IS NULL OR "
            "delivery_tried_at <= now() - make_interval(secs => %s)) ORDER BY settled_at, id LIMIT %s",
            (within_s, retry_s, limit))
        return tuple(Delivery(int(r[0]), int(r[1]), int(r[2]), int(r[3])) for r in rows)

    async def claim(self, wake_id: int, retry_s: float) -> bool:
        return await self._count(
            "UPDATE wakes SET delivery_tried_at = now() WHERE id = %s AND delivery IN ('sending', 'undelivered') "
            "AND dismissed_at IS NULL AND (delivery_tried_at IS NULL OR delivery_tried_at <= now() - "
            "make_interval(secs => %s))", (wake_id, retry_s)) == 1

    async def delivered(self, wake_id: int, reached: bool) -> None:
        await self._count("UPDATE wakes SET delivery = %s, delivery_attempts = delivery_attempts + 1, "
                          "delivery_tried_at = now() WHERE id = %s AND delivery IN ('sending', 'undelivered')",
                          ("delivered" if reached else "undelivered", wake_id))

    async def dismiss(self, household_id: int, person_id: int, wake_id: int) -> bool:
        return await self._count(
            "UPDATE wakes SET dismissed_at = now() WHERE id = %s AND household_id = %s AND settled_at IS NOT NULL "
            "AND " + _LISTED + " AND (person_id = %s OR made_by = %s)",
            (wake_id, household_id, person_id, person_id)) == 1

    async def cancel(self, household_id: int, person_id: int, wake_id: int) -> bool:
        return await self._count(
            "UPDATE wakes SET settled_at = now(), outcome = 'cancelled' WHERE id = %s AND household_id = %s "
            "AND kind = 'reminder' AND settled_at IS NULL AND (person_id = %s OR made_by = %s)",
            (wake_id, household_id, person_id, person_id)) == 1

    async def prune(self, older_than_s: float) -> int:
        return await self._count("DELETE FROM wakes WHERE settled_at < now() - make_interval(secs => %s) "
                                 "AND NOT coalesce(" + _LISTED + ", false)", (older_than_s,))

    async def said_before(self, wake_id: int, person_id: int) -> SaidBefore:
        row = await self._one(_SAID_BEFORE, {"wake": wake_id, "person": person_id, "quiet": QUIET})
        return SaidBefore(None, None, None) if row is None else SaidBefore(row[0], row[1], row[2])

    async def _one(self, query: LiteralString, params: tuple[Any, ...] | dict[str, Any]) -> tuple[Any, ...] | None:
        try:
            async with self._database.connection() as conn:
                cur = await conn.execute(query, params)
                return await cur.fetchone()
        except (DatabaseUnavailable, psycopg.Error) as e:
            raise WakesUnavailable("database unavailable") from e

    async def _all(self, query: LiteralString, params: tuple[Any, ...] | dict[str, Any]) -> list[tuple[Any, ...]]:
        try:
            async with self._database.connection() as conn:
                cur = await conn.execute(query, params)
                return await cur.fetchall()
        except (DatabaseUnavailable, psycopg.Error) as e:
            raise WakesUnavailable("database unavailable") from e

    async def _count(self, query: LiteralString, params: tuple[Any, ...] | dict[str, Any]) -> int:
        try:
            async with self._database.connection() as conn:
                cur = await conn.execute(query, params)
                return cur.rowcount
        except (DatabaseUnavailable, psycopg.Error) as e:
            raise WakesUnavailable("database unavailable") from e
