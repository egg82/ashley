"""Lexicons in Postgres, table `household_lexicon`: one row per household and real spelling. One log line per edit:
household, person, action and the household's word count, never a word."""

import logging
from collections.abc import Generator
from contextlib import contextmanager

import psycopg

from .. import logs
from ..db.database import Database, DatabaseUnavailable
from .lexicon import EMPTY, Lexicon, refusal
from .lexicons import MAX_ENTRIES, Entry, LexiconFull, Lexicons, LexiconUnavailable

log = logging.getLogger("ashley.channels.lexicon")

LOCK = "SELECT 1 FROM households WHERE id = %s FOR UPDATE"
COUNT = "SELECT count(*), count(*) FILTER (WHERE real = %s) FROM household_lexicon WHERE household_id = %s"
UPSERT = ("INSERT INTO household_lexicon (household_id, real, spoken, updated_at, updated_by) "
          "VALUES (%(h)s, %(real)s, %(spoken)s, now(), %(person)s) "
          "ON CONFLICT (household_id, real) DO UPDATE SET spoken = excluded.spoken, updated_at = now(), "
          "updated_by = excluded.updated_by RETURNING real, spoken, updated_at, updated_by")


@contextmanager
def translated() -> Generator[None]:
    try:
        yield
    except DatabaseUnavailable as e:
        raise LexiconUnavailable("no database connection") from e
    except psycopg.Error as e:
        raise LexiconUnavailable("database unreachable") from e


class PostgresLexicons(Lexicons):
    def __init__(self, database: Database) -> None:
        self._database = database

    async def of(self, household_id: int | None) -> Lexicon:
        if household_id is None:
            return EMPTY
        try:
            found = await self.entries(household_id)
            return Lexicon({e.real: e.spoken for e in found})
        except (LexiconUnavailable, ValueError) as e:
            logs.warning(log, "lexicon.unreadable", household=household_id, error=type(e).__name__)
            return EMPTY

    async def entries(self, household_id: int) -> tuple[Entry, ...]:
        with translated():
            async with self._database.connection() as conn:
                cur = await conn.execute("SELECT real, spoken, updated_at, updated_by FROM household_lexicon "
                                         "WHERE household_id = %s ORDER BY real", (household_id,))
                return tuple(Entry(*r) for r in await cur.fetchall())

    async def put(self, household_id: int, person_id: int, real: str, spoken: str) -> Entry:
        why = refusal(real, spoken)
        if why is not None:
            raise ValueError(why)
        with translated():
            async with self._database.connection() as conn:
                await conn.execute(LOCK, (household_id,))
                cur = await conn.execute(COUNT, (real, household_id))
                row = await cur.fetchone()
                assert row is not None
                if row[0] >= MAX_ENTRIES and row[1] == 0:
                    raise LexiconFull(household_id)
                cur = await conn.execute(UPSERT, {"h": household_id, "real": real, "spoken": spoken,
                                                  "person": person_id})
                saved = await cur.fetchone()
                assert saved is not None
                count = row[0] + (1 if row[1] == 0 else 0)
        logs.info(log, "lexicon.changed", household=household_id, person=person_id, action="put", count=count)
        return Entry(*saved)

    async def remove(self, household_id: int, person_id: int, real: str) -> bool:
        with translated():
            async with self._database.connection() as conn:
                cur = await conn.execute("DELETE FROM household_lexicon WHERE household_id = %s AND real = %s",
                                         (household_id, real))
                removed = cur.rowcount == 1
                cur = await conn.execute("SELECT count(*) FROM household_lexicon WHERE household_id = %s",
                                         (household_id,))
                count = (await cur.fetchone() or (0,))[0]
        if removed:
            logs.info(log, "lexicon.changed", household=household_id, person=person_id, action="remove", count=count)
        return removed
