"""Looks in Postgres: table `bench_looks`, one row per tool call that took a look."""

import logging
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC
from typing import Any

import psycopg

from ..db.database import Database, DatabaseUnavailable
from .looks import Look, Looks, LooksUnavailable, NewLook

log = logging.getLogger("ashley.looks")
_LOOK = ("id, household_id, conversation_id, turn_id, call_id, bench_id, piece_id, sha256, media_type, size, "
         "looked_at")


@contextmanager
def _translated() -> Generator[None]:
    try:
        yield
    except DatabaseUnavailable as e:
        raise LooksUnavailable("no database connection") from e
    except psycopg.OperationalError as e:
        raise LooksUnavailable("database unreachable") from e


def _look(row: tuple[Any, ...]) -> Look:
    return Look(row[0], row[1], row[2], row[3], row[4], row[5], row[6], row[7], row[8], row[9],
                row[10].astimezone(UTC))


class PostgresLooks(Looks):
    def __init__(self, database: Database) -> None:
        self._database = database

    async def keep(self, look: NewLook) -> int:
        with _translated():
            async with self._database.connection() as conn:
                cur = await conn.execute(
                    "INSERT INTO bench_looks (household_id, conversation_id, turn_id, call_id, bench_id, piece_id, "
                    "sha256, media_type, size) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
                    "ON CONFLICT (turn_id, call_id) DO UPDATE SET bench_id = EXCLUDED.bench_id, "
                    "piece_id = EXCLUDED.piece_id, sha256 = EXCLUDED.sha256, media_type = EXCLUDED.media_type, "
                    "size = EXCLUDED.size, looked_at = now() RETURNING id",
                    (look.household_id, look.conversation_id, look.turn_id, look.call_id, look.bench_id, look.piece_id,
                     look.sha256, look.media_type, look.size))
                row = await cur.fetchone()
        assert row is not None
        return int(row[0])

    async def taken(self, household_id: int, turn_id: int, except_call: str) -> int:
        with _translated():
            async with self._database.connection() as conn:
                cur = await conn.execute("SELECT count(*) FROM bench_looks WHERE turn_id = %s AND household_id = %s "
                                         "AND call_id <> %s", (turn_id, household_id, except_call))
                row = await cur.fetchone()
        assert row is not None
        return int(row[0])

    async def in_conversation(self, household_id: int, conversation_id: int) -> list[Look]:
        with _translated():
            async with self._database.connection() as conn:
                cur = await conn.execute(f"SELECT {_LOOK} FROM bench_looks WHERE conversation_id = %s AND "
                                         "household_id = %s ORDER BY id", (conversation_id, household_id))
                rows = await cur.fetchall()
        return [_look(row) for row in rows]
