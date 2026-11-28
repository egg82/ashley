"""The outside record in Postgres: `outside_actions`, one row per change she made that nobody asked for in that turn,
with its cause and undo in plain columns (null on rows kept before them) and whether that undo was taken (`undone_*`),
and `outside_writes`, one row per list entity a tainted turn wrote."""

from collections.abc import Sequence
from datetime import datetime
from typing import Any, LiteralString

import psycopg

from ..db.database import Database, DatabaseUnavailable
from ..undo import undo_of
from .outside_record import DoneAction, OutsideRecord, OutsideRecordUnavailable, Recorded, Settled, cause_of, undone_of

_COLUMNS: LiteralString = ("household_id, person_id, conversation_id, turn_id, tool, summary, tier, reason, explanation, at, label, "
            "cause_kind, cause_id, undo_kind, undo_ref, undo_within")
_KEPT: LiteralString = "id, " + _COLUMNS + ", undone_at, undone_by, undone_how"


class PostgresOutsideRecord(OutsideRecord):
    def __init__(self, database: Database, actions_keep_s: float, writes_keep_s: float) -> None:
        self._database = database
        self._actions_keep_s = actions_keep_s
        self._writes_keep_s = writes_keep_s

    async def done(self, action: DoneAction) -> None:
        cause, undo = action.cause, action.undo
        await self._run(
            "WITH made AS (INSERT INTO outside_actions (household_id, person_id, conversation_id, turn_id, tool, summary, "
            "tier, decision, reason, explanation, at, label, cause_kind, cause_id, undo_kind, undo_ref, undo_within) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, 'run', %s, %s, %s, %s, %s, %s, %s, %s, %s)) "
            "DELETE FROM outside_actions WHERE at < now() - make_interval(secs => %s)",
            (action.household_id, action.person_id, action.conversation_id, action.turn_id, action.tool, action.summary,
             action.tier, action.reason, action.explanation, action.at, action.label,
             None if cause is None else cause.kind, None if cause is None else cause.id,
             None if undo is None else undo.kind, None if undo is None else undo.ref,
             None if undo is None else undo.within, self._actions_keep_s))

    async def of_turn(self, conversation_id: int, turn_id: int) -> tuple[DoneAction, ...]:
        rows = await self._rows(
            "SELECT " + _COLUMNS + " FROM outside_actions WHERE conversation_id = %s AND turn_id = %s ORDER BY id",
            (conversation_id, turn_id))
        return tuple(_action(r) for r in rows)

    async def of_person(self, household_id: int, person_id: int, limit: int) -> tuple[Recorded, ...]:
        rows = await self._rows(
            "SELECT " + _KEPT + " FROM outside_actions WHERE household_id = %s AND person_id = %s "
            "ORDER BY at DESC, id DESC LIMIT %s", (household_id, person_id, limit))
        return tuple(_recorded(r) for r in rows)

    async def one(self, household_id: int, person_id: int, action_id: int) -> Recorded | None:
        rows = await self._rows(
            "SELECT " + _KEPT + " FROM outside_actions WHERE id = %s AND household_id = %s AND person_id = %s",
            (action_id, household_id, person_id))
        return _recorded(rows[0]) if rows else None

    async def claim_undo(self, household_id: int, person_id: int, action_id: int, claim_s: float) -> bool:
        rows = await self._rows(
            "UPDATE outside_actions SET undone_at = now(), undone_by = %s, undone_how = 'undoing' "
            "WHERE id = %s AND household_id = %s AND person_id = %s AND undo_kind IS NOT NULL AND (undone_at IS NULL "
            "OR undone_how = 'undoing' AND undone_at < now() - make_interval(secs => %s)) RETURNING id",
            (person_id, action_id, household_id, person_id, claim_s))
        return bool(rows)

    async def settle_undo(self, action_id: int, how: Settled | None) -> None:
        if how is None:
            await self._run("UPDATE outside_actions SET undone_at = NULL, undone_by = NULL, undone_how = NULL "
                            "WHERE id = %s AND undone_how = 'undoing'", (action_id,))
            return
        await self._run("UPDATE outside_actions SET undone_at = now(), undone_how = %s "
                        "WHERE id = %s AND undone_how = 'undoing'", (how, action_id))

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


def _text(value: Any) -> str | None:
    return None if value is None else str(value)


def _recorded(r: tuple[Any, ...]) -> Recorded:
    """A row of `_KEPT` as `Recorded`."""
    return Recorded(int(r[0]), _action(r[1:17]), undone_of(r[17], None if r[18] is None else int(r[18]), _text(r[19])))


def _action(r: tuple[Any, ...]) -> DoneAction:
    """A row of `_COLUMNS` as a `DoneAction`."""
    return DoneAction(int(r[0]), int(r[1]), int(r[2]), int(r[3]), str(r[4]), str(r[5]), str(r[6]), _text(r[7]),
                      _text(r[8]), r[9], str(r[10]), cause_of(_text(r[11]), None if r[12] is None else int(r[12])),
                      undo_of(_text(r[13]), _text(r[14]), _text(r[15])))
