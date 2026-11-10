"""Claims in Postgres, table `discord_seen`."""

from datetime import datetime

import psycopg

from ...db.database import Database, DatabaseUnavailable
from .seen import Seen, SeenUnavailable


class PostgresSeen(Seen):
    def __init__(self, database: Database) -> None:
        self._database = database

    async def claim(self, message_id: int, channel_id: int) -> bool:
        try:
            async with self._database.connection() as conn:
                cur = await conn.execute(
                    "INSERT INTO discord_seen (message_id, channel_id) VALUES (%s, %s) "
                    "ON CONFLICT (message_id) DO NOTHING RETURNING message_id",
                    (message_id, channel_id),
                )
                return await cur.fetchone() is not None
        except (DatabaseUnavailable, psycopg.Error) as e:
            raise SeenUnavailable("database unavailable") from e

    async def last(self, since: datetime) -> dict[int, int]:
        try:
            async with self._database.connection() as conn:
                cur = await conn.execute(
                    "SELECT channel_id, max(message_id) FROM discord_seen WHERE claimed_at >= %s GROUP BY channel_id",
                    (since,),
                )
                rows = await cur.fetchall()
        except (DatabaseUnavailable, psycopg.Error) as e:
            raise SeenUnavailable("database unavailable") from e
        return {row[0]: row[1] for row in rows}

    async def prune(self, before: datetime) -> int:
        try:
            async with self._database.connection() as conn:
                cur = await conn.execute("DELETE FROM discord_seen WHERE claimed_at < %s", (before,))
                return cur.rowcount
        except (DatabaseUnavailable, psycopg.Error) as e:
            raise SeenUnavailable("database unavailable") from e

    async def settle(self, message_id: int) -> None:
        try:
            async with self._database.connection() as conn:
                await conn.execute("UPDATE discord_seen SET settled_at = now() WHERE message_id = %s "
                                   "AND settled_at IS NULL", (message_id,))
        except (DatabaseUnavailable, psycopg.Error) as e:
            raise SeenUnavailable("database unavailable") from e

    async def unsettled(self, since: datetime) -> dict[int, int]:
        try:
            async with self._database.connection() as conn:
                cur = await conn.execute("SELECT message_id, channel_id FROM discord_seen WHERE claimed_at >= %s "
                                         "AND settled_at IS NULL", (since,))
                rows = await cur.fetchall()
        except (DatabaseUnavailable, psycopg.Error) as e:
            raise SeenUnavailable("database unavailable") from e
        return {row[0]: row[1] for row in rows}
