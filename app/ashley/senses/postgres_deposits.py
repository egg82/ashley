"""Deposits in Postgres: armed reminders are rows of `wakes` (trigger `event`), the cursor is `deposit_reads`, and
whether a balance rule's account is below now is `balance_lows`."""

from datetime import date
from typing import Any, LiteralString

import psycopg
from psycopg.types.json import Jsonb

from ..db.database import Database, DatabaseUnavailable
from .deposit_rule import DepositRule, Landed, from_json, landed_to_json, to_json
from .deposits import Armed, Deposits, DepositsUnavailable
from .wakes import MAX_BRIEF, Reminder


class PostgresDeposits(Deposits):
    def __init__(self, database: Database) -> None:
        self._database = database

    async def arm(self, reminder: Reminder, rule: DepositRule) -> int:
        if not 1 <= len(reminder.brief) <= MAX_BRIEF or "\x00" in reminder.brief or reminder.repeat is not None:
            raise ValueError(f"an armed reminder's brief is 1 to {MAX_BRIEF} characters, without a NUL, and it has no repeat")
        made = await self._one(
            "INSERT INTO wakes (household_id, kind, trigger, event_id, event, at, due_at, person_id, made_by, brief, "
            "deposit_rule, route, tools, taint, made_conversation_id, made_turn_id, route_device_id) VALUES (%s, 'reminder', "
            "'event', 'armed:' || gen_random_uuid(), 'reminder', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (reminder.household_id, reminder.due_at, reminder.due_at, reminder.person_id, reminder.made_by,
             reminder.brief, Jsonb(to_json(rule)), reminder.route,
             None if reminder.tools is None else list(reminder.tools), reminder.taint,
             *((None, None) if reminder.made_in is None else reminder.made_in), reminder.device_id))
        if made is None:
            raise DepositsUnavailable("the reminder was not stored")
        return int(made[0])

    async def armed(self) -> tuple[Armed, ...]:
        rows = await self._all("SELECT id, household_id, deposit_rule, due_at FROM wakes WHERE trigger = 'event' "
                               "AND settled_at IS NULL ORDER BY id", ())
        return tuple(Armed(int(r[0]), int(r[1]), from_json(r[2]), r[3]) for r in rows)

    async def fire(self, armed_id: int, transaction_id: str, landed: Landed | None = None) -> bool:
        made = await self._one(
            "INSERT INTO wakes (household_id, kind, event_id, event, at, due_at, person_id, made_by, brief, landed, "
            "route, tools, taint, made_conversation_id, made_turn_id, route_device_id) "
            "SELECT household_id, 'reminder', 'deposit:' || id || ':' || %s, 'reminder', now(), now(), person_id, "
            "made_by, brief, %s, route, tools, taint, made_conversation_id, made_turn_id, route_device_id FROM wakes WHERE id = %s AND trigger = 'event' AND settled_at IS NULL "
            "ON CONFLICT (household_id, event_id) DO NOTHING RETURNING id",
            (transaction_id, None if landed is None else Jsonb(landed_to_json(landed)), armed_id))
        return made is not None

    async def below(self, armed_id: int, landed: Landed) -> bool:
        made = await self._one(
            "WITH fell AS (INSERT INTO balance_lows (armed_id, low, episode) SELECT id, true, 1 FROM wakes "
            "WHERE id = %s AND trigger = 'event' AND settled_at IS NULL "
            "ON CONFLICT (armed_id) DO UPDATE SET low = true, episode = balance_lows.episode + 1 "
            "WHERE NOT balance_lows.low RETURNING armed_id, episode) "
            "INSERT INTO wakes (household_id, kind, event_id, event, at, due_at, person_id, made_by, brief, landed, "
            "route, tools, taint, made_conversation_id, made_turn_id, route_device_id) "
            "SELECT household_id, 'reminder', 'balance:' || id || ':' || fell.episode, 'reminder', now(), now(), "
            "person_id, made_by, brief, %s, route, tools, taint, made_conversation_id, made_turn_id, route_device_id "
            "FROM wakes JOIN fell ON fell.armed_id = wakes.id "
            "ON CONFLICT (household_id, event_id) DO NOTHING RETURNING id",
            (armed_id, Jsonb(landed_to_json(landed))))
        return made is not None

    async def recovered(self, armed_id: int) -> None:
        await self._one("UPDATE balance_lows SET low = false WHERE armed_id = %s AND low", (armed_id,))

    async def read_through(self, household_id: int) -> date | None:
        got = await self._one("SELECT read_through FROM deposit_reads WHERE household_id = %s", (household_id,))
        return None if got is None else got[0]

    async def advance(self, household_id: int, day: date) -> None:
        await self._one("INSERT INTO deposit_reads (household_id, read_through) VALUES (%s, %s) "
                        "ON CONFLICT (household_id) DO UPDATE SET read_through = greatest(deposit_reads.read_through, "
                        "excluded.read_through)", (household_id, day))

    async def _one(self, query: LiteralString, params: tuple[Any, ...]) -> tuple[Any, ...] | None:
        try:
            async with self._database.connection() as conn:
                cur = await conn.execute(query, params)
                return await cur.fetchone() if cur.description is not None else None
        except (DatabaseUnavailable, psycopg.Error) as e:
            raise DepositsUnavailable("database unavailable") from e

    async def _all(self, query: LiteralString, params: tuple[Any, ...]) -> list[tuple[Any, ...]]:
        try:
            async with self._database.connection() as conn:
                cur = await conn.execute(query, params)
                return await cur.fetchall()
        except (DatabaseUnavailable, psycopg.Error) as e:
            raise DepositsUnavailable("database unavailable") from e
