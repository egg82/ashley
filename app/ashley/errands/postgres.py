"""Errands in Postgres, table `errands`."""

from collections.abc import Collection
from typing import Any, LiteralString

import psycopg

from ..db.database import Database, DatabaseUnavailable
from ..hearing import MAY_HEAR
from .errands import Errands, ErrandsUnavailable
from .model import Counts, Done, Errand, Reason, State, Visibility

_OWE = """
INSERT INTO errands (household_id, asker_id, conversation_id, turn_id, source, visibility)
SELECT t.household_id, %s, t.conversation_id, t.id, %s, t.visibility FROM turns t
WHERE t.id = %s AND t.conversation_id = %s AND t.household_id = %s
ON CONFLICT (turn_id) DO NOTHING RETURNING id"""

HOLD = """
INSERT INTO errands (household_id, asker_id, conversation_id, turn_id, source, state, result, visibility, finished_at)
SELECT t.household_id, t.speaker_id, t.conversation_id, t.id, 'outbox', 'done', %s, t.visibility, now() FROM turns t
WHERE t.id = %s AND t.speaker_id IS NOT NULL
ON CONFLICT (turn_id) DO NOTHING"""
"""An answer she could not deliver in time, held as a `done` errand of the asker's, source `outbox`, so her next reply to
them tells it (`PostgresOutbox.take`, in its own transaction). Parameters: the answer's text, the person turn it answers."""

_CLAIM = """
UPDATE errands SET state = 'running', attempts = attempts + 1, claimed_at = now()
WHERE id = (SELECT id FROM errands
            WHERE state = 'due' AND source = ANY(%s) AND created_at > now() - make_interval(secs => %s)
            ORDER BY created_at, id LIMIT 1 FOR UPDATE SKIP LOCKED)
RETURNING id, household_id, asker_id, conversation_id, turn_id, source, attempts, visibility"""

_RELEASE = """
UPDATE errands SET
    state = CASE WHEN attempts >= %(max)s THEN 'given_up' ELSE 'due' END,
    reason = CASE WHEN attempts >= %(max)s THEN 'attempts' END,
    finished_at = CASE WHEN attempts >= %(max)s THEN now() END,
    claimed_at = CASE WHEN attempts >= %(max)s THEN claimed_at END
WHERE id = %(id)s AND state = 'running' AND attempts = %(attempt)s RETURNING state"""

_SETTLE = """
UPDATE errands SET state = %(state)s, result = %(result)s, reason = %(reason)s, finished_at = now()
WHERE id = %(id)s AND state = 'running' AND attempts = %(attempt)s"""

_SWEEP = """
WITH interrupted AS (
    UPDATE errands SET state = 'given_up', reason = 'interrupted', finished_at = now()
    WHERE state = 'running' AND claimed_at < now() - make_interval(secs => %(claim)s) RETURNING 1),
expired AS (
    UPDATE errands SET state = 'given_up', reason = 'expired', finished_at = now()
    WHERE state = 'due' AND created_at < now() - make_interval(secs => %(age)s) RETURNING 1)
SELECT (SELECT count(*) FROM interrupted), (SELECT count(*) FROM expired)"""

_DUE_SOURCES = """
SELECT DISTINCT source FROM errands
WHERE state = 'due' AND created_at > now() - make_interval(secs => %s)"""

_UNTOLD = f"""
SELECT id, asker_id, source, result, visibility, finished_at
FROM (SELECT *, asker_id AS owner_id FROM errands) e
WHERE state = 'done' AND told_at IS NULL AND asker_id = %(speaker)s AND {MAY_HEAR}
ORDER BY finished_at, id LIMIT %(limit)s"""


class PostgresErrands(Errands):
    def __init__(self, database: Database) -> None:
        self._database = database

    async def owe(self, household_id: int, asker_id: int, conversation_id: int, turn_id: int, source: str) -> int:
        rows = await self._run(_OWE, (asker_id, source, turn_id, conversation_id, household_id))
        if rows:
            return int(rows[0][0])
        rows = await self._run("SELECT id FROM errands WHERE turn_id = %s", (turn_id,))
        if not rows:
            raise ValueError("the turn is not in that household's conversation")
        return int(rows[0][0])

    async def claim(self, answering: Collection[str], max_age_s: float) -> Errand | None:
        if not answering:
            return None
        rows = await self._run(_CLAIM, (list(answering), max_age_s))
        if not rows:
            return None
        r = rows[0]
        return Errand(int(r[0]), int(r[1]), int(r[2]), int(r[3]), int(r[4]), str(r[5]), int(r[6]), _visibility(r[7]))

    async def due_sources(self, max_age_s: float) -> frozenset[str]:
        return frozenset(str(r[0]) for r in await self._run(_DUE_SOURCES, (max_age_s,)))

    async def release(self, errand_id: int, attempt: int, max_attempts: int) -> State:
        rows = await self._run(_RELEASE, {"id": errand_id, "attempt": attempt, "max": max_attempts})
        if rows:
            return _state(rows[0][0])
        found = await self._run("SELECT state FROM errands WHERE id = %s", (errand_id,))
        if not found:
            raise LookupError("no such errand")
        return _state(found[0][0])

    async def finish(self, errand_id: int, attempt: int, result: str) -> None:
        await self._run(_SETTLE, {"id": errand_id, "attempt": attempt, "state": "done", "result": result,
                                  "reason": None})

    async def give_up(self, errand_id: int, attempt: int, reason: Reason) -> None:
        await self._run(_SETTLE, {"id": errand_id, "attempt": attempt, "state": "given_up", "result": None,
                                  "reason": reason})

    async def sweep(self, claim_s: float, max_age_s: float) -> Counts:
        rows = await self._run(_SWEEP, {"claim": claim_s, "age": max_age_s})
        return Counts(int(rows[0][0]), int(rows[0][1]))

    async def untold(self, hearer: int, limit: int, owner_only: bool = True) -> tuple[Done, ...]:
        rows = await self._run(_UNTOLD, {"speaker": hearer, "owner_only": owner_only, "limit": limit})
        return tuple(Done(int(r[0]), int(r[1]), str(r[2]), str(r[3]), _visibility(r[4]), r[5]) for r in rows)

    async def told(self, errand_ids: Collection[int]) -> None:
        if errand_ids:
            await self._run("UPDATE errands SET told_at = now() WHERE id = ANY(%s) AND told_at IS NULL",
                            (list(errand_ids),))

    async def _run(self, query: LiteralString, params: tuple[Any, ...] | dict[str, Any]) -> list[tuple[Any, ...]]:
        try:
            async with self._database.connection() as conn:
                cur = await conn.execute(query, params)
                return await cur.fetchall() if cur.description is not None else []
        except (DatabaseUnavailable, psycopg.Error) as e:
            raise ErrandsUnavailable("database unavailable") from e


def _state(raw: Any) -> State:
    if raw not in ("due", "running", "done", "given_up"):
        raise ErrandsUnavailable("unknown state")
    return raw


def _visibility(raw: Any) -> Visibility:
    return "private" if raw != "shared" else "shared"
