"""Watches in Postgres, tables `watches` and (for the wakes a check stores) `wakes`."""

import re
from datetime import UTC, datetime
from typing import Any, LiteralString

import psycopg
from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from ..criteria import condition
from ..db.database import Database, DatabaseUnavailable
from . import rows
from .config import CONFIG, WatchesConfig
from .model import MAX_BRIEF, Arm, Armed, Baseline, Check, Counts, Failed, Later, Watch, Woke
from .watches import Watches, WatchesUnavailable

_KIND = re.compile(r"^[a-z][a-z0-9_]{0,63}$")

_STORE_WAKE = """
INSERT INTO wakes (household_id, kind, event_id, event, what, at, due_at, person_id, watch_id, changes)
VALUES (%s, 'watch', %s, 'watch', %s, now(), now(), %s, %s, %s) ON CONFLICT (household_id, event_id) DO NOTHING"""

_SETTLE = """
UPDATE watches SET
    baseline = CASE WHEN %(store)s THEN %(baseline)s::jsonb ELSE baseline END,
    version = version + (%(store)s)::int,
    series = series + (%(woke)s)::int,
    last_woke_at = CASE WHEN %(woke)s THEN now() ELSE last_woke_at END,
    failures = 0,
    state = CASE WHEN %(ends)s THEN 'ended' ELSE 'armed' END,
    reason = CASE WHEN %(ends)s THEN 'until' END,
    ended_at = CASE WHEN %(ends)s THEN now() END,
    expires_at = CASE WHEN standing_s IS NULL THEN expires_at ELSE now() + make_interval(secs => standing_s) END,
    next_check_at = now() + make_interval(secs => interval_s)
WHERE id = %(id)s"""

_FAIL = """
UPDATE watches SET
    failures = failures + 1,
    state = CASE WHEN state = 'paused' OR failures + 1 >= %(after)s THEN 'paused' ELSE 'armed' END,
    reason = CASE WHEN state = 'paused' OR failures + 1 >= %(after)s THEN %(reason)s END,
    next_check_at = now() + make_interval(secs => CASE WHEN state = 'paused' OR failures + 1 >= %(after)s
                                                       THEN %(retry)s ELSE interval_s END)
WHERE id = %(id)s"""

_LATER = "UPDATE watches SET next_check_at = now() + make_interval(secs => %s) WHERE id = %s"

_LOCK = """
SELECT household_id, person_id, state, series, version, coalesce(last_woke_at, armed_at), failures FROM watches
WHERE id = %s AND version = %s AND state IN ('armed', 'paused') FOR UPDATE"""

_INSERT = """
INSERT INTO watches (household_id, person_id, kind, target, label, bench_id, armed_by, track, when_clauses,
                     until_clauses, tools, interval_s, expires_at, baseline, brief, standing_s, taint, made_conversation_id,
                     made_turn_id)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id"""

_UPDATE = """
UPDATE watches SET when_clauses = %s, until_clauses = %s, tools = %s, interval_s = %s, expires_at = %s,
    brief = %s, standing_s = %s, taint = COALESCE(%s, taint), made_conversation_id = COALESCE(%s, made_conversation_id),
    made_turn_id = COALESCE(%s, made_turn_id), bench_id = %s, armed_by = CASE WHEN armed_by = 'handoff' OR %s = 'handoff' THEN 'handoff' ELSE 'ashley' END
WHERE id = %s"""

_EXPIRE = """
WITH e AS (UPDATE watches SET state = 'ended', reason = 'expired', ended_at = now()
           WHERE state <> 'ended' AND expires_at <= now() RETURNING 1),
d AS (DELETE FROM watches w WHERE state = 'ended' AND ended_at < now() - make_interval(secs => %s)
      AND NOT EXISTS (SELECT 1 FROM wakes k WHERE k.watch_id = w.id AND k.settled_at IS NULL) RETURNING 1)
SELECT (SELECT count(*) FROM e), (SELECT count(*) FROM d)"""

_DUE = f"""
SELECT {rows.COLUMNS} FROM watches w WHERE state <> 'ended' AND expires_at > now() AND next_check_at <= now()
AND NOT EXISTS (SELECT 1 FROM wakes k WHERE k.watch_id = w.id AND k.settled_at IS NULL)
ORDER BY next_check_at, id LIMIT %s"""


class PostgresWatches(Watches):
    def __init__(self, database: Database, config: WatchesConfig = CONFIG) -> None:
        self._database = database
        self._config = config

    async def arm(self, arm: Arm) -> Armed:
        self._checked(arm)
        try:
            async with self._database.connection() as conn:
                return await self._store(conn, arm)
        except (DatabaseUnavailable, psycopg.Error) as e:
            raise WatchesUnavailable("database unavailable") from e

    async def _store(self, conn: AsyncConnection[tuple[Any, ...]], arm: Arm) -> Armed:
        until = None if arm.until is None else Jsonb(condition.to_json(arm.until))
        tools = None if arm.tools is None else list(arm.tools)
        standing_s = (arm.expires_at - datetime.now(UTC)).total_seconds() if arm.standing else None
        made = (None, None) if arm.made_in is None else arm.made_in
        cur = await conn.execute("SELECT 1 FROM people WHERE id = %s AND household_id = %s FOR UPDATE",
                                 (arm.person_id, arm.household_id))
        if await cur.fetchone() is None:
            raise ValueError("no such person in that household")
        cur = await conn.execute("SELECT id FROM watches WHERE person_id = %s AND kind = %s AND target = %s "
                                 "AND state <> 'ended' FOR UPDATE", (arm.person_id, arm.kind, arm.target))
        found = await cur.fetchone()
        if found is not None:
            await conn.execute(_UPDATE, (Jsonb(condition.to_json(arm.when)), until, tools, arm.interval_s,
                                         arm.expires_at, arm.brief, standing_s, arm.taint, *made, arm.bench_id,
                                         arm.armed_by, found[0]))
            return Armed(int(found[0]), False)
        cur = await conn.execute("SELECT count(*) FROM watches WHERE person_id = %s AND state <> 'ended'",
                                 (arm.person_id,))
        if int((await cur.fetchone() or (0,))[0]) >= self._config.max_live:
            raise ValueError(f"a person keeps at most {self._config.max_live} watches")
        cur = await conn.execute(_INSERT, (
            arm.household_id, arm.person_id, arm.kind, arm.target, arm.label, arm.bench_id, arm.armed_by,
            list(arm.track), Jsonb(condition.to_json(arm.when)), until, tools, arm.interval_s, arm.expires_at,
            None if arm.baseline is None else Jsonb(arm.baseline), arm.brief, standing_s, arm.taint, *made))
        made = await cur.fetchone()
        if made is None:
            raise WatchesUnavailable("the watch was not stored")
        return Armed(int(made[0]), True)

    async def disarm(self, household_id: int, person_id: int, kind: str, target: str) -> bool:
        got = await self._run("UPDATE watches SET state = 'ended', reason = 'disarmed', ended_at = now() "
                              "WHERE household_id = %s AND person_id = %s AND kind = %s AND target = %s "
                              "AND state <> 'ended' RETURNING id", (household_id, person_id, kind, target))
        return len(got) == 1

    async def live(self, household_id: int, person_id: int) -> tuple[Watch, ...]:
        got = await self._run(f"SELECT {rows.COLUMNS} FROM watches WHERE household_id = %s AND person_id = %s "
                              "AND state <> 'ended' ORDER BY expires_at, id", (household_id, person_id))
        return tuple(rows.watch(r) for r in got)

    async def get(self, watch_id: int) -> Watch | None:
        got = await self._run(f"SELECT {rows.COLUMNS} FROM watches WHERE id = %s", (watch_id,))
        return rows.watch(got[0]) if got else None

    async def due(self, limit: int) -> tuple[Watch, ...]:
        return tuple(rows.watch(r) for r in await self._run(_DUE, (limit,)))

    async def record(self, watch_id: int, version: int, check: Check) -> bool:
        try:
            async with self._database.connection() as conn:
                cur = await conn.execute(_LOCK, (watch_id, version))
                locked = await cur.fetchone()
                if locked is None:
                    return False
                await self._apply(conn, watch_id, locked, check)
                return True
        except (DatabaseUnavailable, psycopg.Error) as e:
            raise WatchesUnavailable("database unavailable") from e

    async def expire(self, keep_s: float) -> Counts:
        got = await self._run(_EXPIRE, (keep_s,))
        return Counts(int(got[0][0]), int(got[0][1]))

    async def _apply(self, conn: AsyncConnection[tuple[Any, ...]], watch_id: int, locked: tuple[Any, ...],
                     check: Check) -> None:
        if isinstance(check, Failed):
            await self._fail(conn, watch_id, locked, check)
            return
        if isinstance(check, Later):
            await conn.execute(_LATER, (self._config.retry_s, watch_id))
            return
        woke = isinstance(check, Woke)
        items = check.items if isinstance(check, Baseline | Woke) else None
        ends = not isinstance(check, Baseline) and check.ends
        await conn.execute(_SETTLE, {"id": watch_id, "store": items is not None, "woke": woke, "ends": ends,
                                     "baseline": None if items is None else Jsonb(items)})
        if isinstance(check, Woke):
            series, version = int(locked[3]) + 1, int(locked[4]) + 1
            await conn.execute(_STORE_WAKE, (locked[0], f"watch:{watch_id}:{version}", "changed", locked[1], watch_id,
                                             Jsonb(rows.changed_wake(series, locked[5], check.ends, check.changes))))

    async def _fail(self, conn: AsyncConnection[tuple[Any, ...]], watch_id: int, locked: tuple[Any, ...],
                    check: Failed) -> None:
        after = self._config.fail_after
        await conn.execute(_FAIL, {"id": watch_id, "after": after, "retry": self._config.retry_s,
                                   "reason": check.reason})
        if locked[2] == "armed" and int(locked[6]) + 1 >= after:
            cur = await conn.execute("SELECT gen_random_uuid()")
            salt = (await cur.fetchone() or ("",))[0]
            await conn.execute(_STORE_WAKE, (locked[0], f"watch:{watch_id}:paused:{salt}", "paused", locked[1],
                                             watch_id, Jsonb({"what": "paused", "reason": check.reason})))

    def _checked(self, arm: Arm) -> None:
        c = self._config
        if not (1 <= len(arm.target) <= 200 and 1 <= len(arm.label) <= 100 and 1 <= len(arm.track) <= 8
                and arm.interval_s > 0 and _KIND.match(arm.kind) is not None and "\x00" not in arm.target + arm.label):
            raise ValueError("a watch has a kind, a target of 1 to 200 characters, a label of 1 to 100, 1 to 8 "
                             "tracked fields and a positive interval")
        if arm.tools is not None and len(arm.tools) > 20:
            raise ValueError("a watch has at most 20 tools")
        if arm.brief is not None and not (1 <= len(arm.brief) <= MAX_BRIEF and "\x00" not in arm.brief):
            raise ValueError(f"a watch's brief is 1 to {MAX_BRIEF} characters, without a NUL")
        if arm.expires_at.tzinfo is None or arm.expires_at <= datetime.now(UTC):
            raise ValueError("a watch expires in the future")
        if arm.baseline is not None and len(arm.baseline) > c.max_items:
            raise ValueError(f"a baseline has at most {c.max_items} items")
        for cond in (arm.when, *([] if arm.until is None else [arm.until])):
            condition.validate(cond, arm.track, c.max_alternatives, c.max_predicates)

    async def _run(self, query: LiteralString, params: tuple[Any, ...]) -> list[tuple[Any, ...]]:
        try:
            async with self._database.connection() as conn:
                cur = await conn.execute(query, params)
                return await cur.fetchall() if cur.description is not None else []
        except (DatabaseUnavailable, psycopg.Error) as e:
            raise WatchesUnavailable("database unavailable") from e
