"""The outside record in Postgres: `outside_actions`, one row per change a tainted turn made with no OK, and
`outside_writes`, one row per list entity a tainted turn wrote."""

from collections.abc import Sequence
from datetime import datetime
from typing import Any, LiteralString

import psycopg

from ..db.database import Database, DatabaseUnavailable
from .outside_record import DoneAction, OutsideRecord, OutsideRecordUnavailable, Recorded


class PostgresOutsideRecord(OutsideRecord):
    def __init__(self, database: Database, actions_keep_s: float, writes_keep_s: float) -> None:
        self._database = database
        self._actions_keep_s = actions_keep_s
        self._writes_keep_s = writes_keep_s

    async def done(self, action: DoneAction) -> None:
        await self._run(
            "WITH made AS (INSERT INTO outside_actions (household_id, person_id, conversation_id, turn_id, tool, summary, "
            "tier, decision, reason, explanation, at, label) VALUES (%s, %s, %s, %s, %s, %s, %s, 'run', %s, %s, %s, %s)) "
            "DELETE FROM outside_actions WHERE at < now() - make_interval(secs => %s)",
            (action.household_id, action.person_id, action.conversation_id, action.turn_id, action.tool, action.summary,
             action.tier, action.reason, action.explanation, action.at, action.label, self._actions_keep_s))

    async def of_turn(self, conversation_id: int, turn_id: int) -> tuple[DoneAction, ...]:
        rows = await self._rows(
            "SELECT household_id, person_id, conversation_id, turn_id, tool, summary, tier, reason, explanation, at, label "
            "FROM outside_actions WHERE conversation_id = %s AND turn_id = %s ORDER BY id", (conversation_id, turn_id))
        return tuple(DoneAction(int(r[0]), int(r[1]), int(r[2]), int(r[3]), str(r[4]), str(r[5]), str(r[6]),
                                None if r[7] is None else str(r[7]), None if r[8] is None else str(r[8]), r[9], str(r[10]))
                     for r in rows)

    async def of_person(self, household_id: int, person_id: int, limit: int) -> tuple[Recorded, ...]:
        rows = await self._rows(
            "SELECT id, household_id, person_id, conversation_id, turn_id, tool, summary, tier, reason, explanation, at, label "
            "FROM outside_actions WHERE household_id = %s AND person_id = %s ORDER BY at DESC, id DESC LIMIT %s",
            (household_id, person_id, limit))
        return tuple(Recorded(int(r[0]), DoneAction(int(r[1]), int(r[2]), int(r[3]), int(r[4]), str(r[5]), str(r[6]),
                                                    str(r[7]), None if r[8] is None else str(r[8]),
                                                    None if r[9] is None else str(r[9]), r[10], str(r[11])))
                     for r in rows)

    async def wrote(self, household_id: int, entity: str, at: datetime) -> None:
        await self._run(
            "WITH made AS (INSERT INTO outside_writes (household_id, entity, at) VALUES (%s, %s, %s) "
            "ON CONFLICT (household_id, entity) DO UPDATE SET at = excluded.at) "
            "DELETE FROM outside_writes WHERE at < now() - make_interval(secs => %s)",
            (household_id, entity, at, self._writes_keep_s))

    async def written(self, household_id: int, entities: Sequence[str]) -> bool:
        rows = await self._rows(
            "SELECT 1 FROM outside_writes WHERE household_id = %s AND entity = ANY(%s) "
            "AND at > now() - make_interval(secs => %s) LIMIT 1", (household_id, list(entities), self._writes_keep_s))
        return bool(rows)

    async def _run(self, query: LiteralString, params: tuple[Any, ...]) -> None:
        try:
            async with self._database.connection() as conn:
                await conn.execute(query, params)
        except (DatabaseUnavailable, psycopg.Error) as e:
            raise OutsideRecordUnavailable("database unavailable") from e

    async def _rows(self, query: LiteralString, params: tuple[Any, ...]) -> list[tuple[Any, ...]]:
        try:
            async with self._database.connection() as conn:
                cur = await conn.execute(query, params)
                return await cur.fetchall()
        except (DatabaseUnavailable, psycopg.Error) as e:
            raise OutsideRecordUnavailable("database unavailable") from e
