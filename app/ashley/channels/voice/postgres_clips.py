"""Clips in Postgres, table `voice_clips`, kept `retention_s` (`voice.json`, `clip_retention_s`)."""

import hashlib
import secrets

import psycopg

from ...db.database import Database, DatabaseUnavailable
from .clips import Clip, Clips, ClipsUnavailable, NewClip


def _sha256(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()


class PostgresClips(Clips):
    def __init__(self, database: Database, retention_s: int) -> None:
        self._database = database
        self._retention_s = retention_s

    async def add(self, device_id: int, body: str, since_wake_ms: int, line: str | None = None) -> NewClip:
        token = secrets.token_urlsafe(32)
        try:
            async with self._database.connection() as conn:
                await conn.execute(
                    "DELETE FROM voice_clips WHERE created_at < clock_timestamp() - make_interval(secs => %s)",
                    (self._retention_s,),
                )
                cur = await conn.execute(
                    "INSERT INTO voice_clips (token_sha256, household_id, device_id, body, line, woke_at) "
                    "SELECT %s, household_id, id, %s, %s, clock_timestamp() - make_interval(secs => %s) FROM devices "
                    "WHERE id = %s RETURNING id",
                    (_sha256(token), body, line, since_wake_ms / 1000, device_id),
                )
                row = await cur.fetchone()
        except (DatabaseUnavailable, psycopg.Error) as e:
            raise ClipsUnavailable("database unreachable") from e
        assert row is not None
        return NewClip(row[0], token)

    async def get(self, token: str) -> Clip | None:
        try:
            async with self._database.connection() as conn:
                cur = await conn.execute(
                    "SELECT id, device_id, body, "
                    "(extract(epoch FROM clock_timestamp() - woke_at) * 1000)::bigint, line FROM voice_clips "
                    "WHERE token_sha256 = %s AND created_at >= clock_timestamp() - make_interval(secs => %s)",
                    (_sha256(token), self._retention_s),
                )
                row = await cur.fetchone()
        except (DatabaseUnavailable, psycopg.Error) as e:
            raise ClipsUnavailable("database unreachable") from e
        return None if row is None else Clip(row[0], row[1], row[2], row[3], row[4])
