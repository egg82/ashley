"""The psycopg 3 async pool behind `Database`."""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool, PoolTimeout

from .. import logs
from .database import Database, DatabaseUnavailable, Probe

log = logging.getLogger("ashley.db")


class PoolDatabase(Database):
    def __init__(self, conninfo: str, probe_timeout_s: float = 2.0, connect_timeout_s: float = 5.0) -> None:
        self._pool = AsyncConnectionPool(conninfo, min_size=1, max_size=5, open=False)
        self._probe_timeout_s = probe_timeout_s
        self._connect_timeout_s = connect_timeout_s

    async def open(self) -> None:
        await self._pool.open(wait=False)

    async def close(self) -> None:
        await self._pool.close()

    async def probe(self) -> Probe:
        try:
            async with self._pool.connection(timeout=self._probe_timeout_s) as conn:
                cur = await conn.execute("SHOW transaction_read_only")
                row = await cur.fetchone()
        except Exception:
            logs.error(log, "db.probe_failed", exc=True)
            return Probe(reachable=False, writable=False)
        return Probe(reachable=True, writable=row is not None and row[0] == "off")

    @asynccontextmanager
    async def connection(self) -> AsyncGenerator[AsyncConnection[tuple[Any, ...]]]:
        try:
            async with self._pool.connection(timeout=self._connect_timeout_s) as conn:
                yield conn
        except PoolTimeout as e:
            raise DatabaseUnavailable("no connection in time") from e
