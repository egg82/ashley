"""Remarks in Postgres, table `remarks`."""

from datetime import datetime

import psycopg

from ..db.database import Database, DatabaseUnavailable
from .remarks import Before, Remarks, RemarksUnavailable


class PostgresRemarks(Remarks):
    def __init__(self, database: Database) -> None:
        self._database = database

    async def before(self, household_id: int, person_id: int, count_since: datetime, said_since: datetime) -> Before:
        try:
            async with self._database.connection() as conn:
                cur = await conn.execute(
                    "SELECT count(*) FROM remarks WHERE household_id = %s AND person_id = %s AND claimed_at >= %s "
                    "AND (NOT settled OR line IS NOT NULL)", (household_id, person_id, count_since))
                counted = await cur.fetchone()
                cur = await conn.execute(
                    "SELECT line FROM remarks WHERE household_id = %s AND claimed_at >= %s AND line IS NOT NULL "
                    "ORDER BY claimed_at", (household_id, said_since))
                lines = await cur.fetchall()
        except (DatabaseUnavailable, psycopg.Error) as e:
            raise RemarksUnavailable("database unavailable") from e
        return Before(0 if counted is None else int(counted[0]), tuple(str(row[0]) for row in lines))

    async def claim(self, household_id: int, person_id: int, source: str, at: datetime) -> bool:
        try:
            async with self._database.connection() as conn:
                cur = await conn.execute(
                    "INSERT INTO remarks (household_id, source, person_id, claimed_at) VALUES (%s, %s, %s, %s) "
                    "ON CONFLICT (household_id, source) DO NOTHING RETURNING source",
                    (household_id, source, person_id, at))
                return await cur.fetchone() is not None
        except (DatabaseUnavailable, psycopg.Error) as e:
            raise RemarksUnavailable("database unavailable") from e

    async def settle(self, household_id: int, source: str, line: str | None) -> None:
        try:
            async with self._database.connection() as conn:
                await conn.execute("UPDATE remarks SET settled = true, line = %s WHERE household_id = %s "
                                   "AND source = %s AND NOT settled", (line, household_id, source))
        except (DatabaseUnavailable, psycopg.Error) as e:
            raise RemarksUnavailable("database unavailable") from e

    async def prune(self, before: datetime) -> int:
        try:
            async with self._database.connection() as conn:
                cur = await conn.execute("DELETE FROM remarks WHERE claimed_at < %s", (before,))
                return cur.rowcount
        except (DatabaseUnavailable, psycopg.Error) as e:
            raise RemarksUnavailable("database unavailable") from e
