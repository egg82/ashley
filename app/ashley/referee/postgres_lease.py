"""`Lease` on Postgres session advisory locks, for a deployment without etcd: one machine, or several replicas sharing
one Postgres. Each singleton name is one lock, keyed `hashtextextended('ashley/singletons/' || name, 0)`; holding the
lock in a session is holding the singleton."""

import asyncio
import logging
import socket
from typing import Any

import psycopg
from psycopg import AsyncConnection

from .. import logs
from .lease import Body, Lease
from .lease_log import Streak, log_outcome, outcome

log = logging.getLogger("ashley.referee")

PREFIX = "ashley/singletons/"

_Conn = AsyncConnection[tuple[Any, ...]]
_FAILURES = (psycopg.Error, OSError, TimeoutError)


class PostgresLease(Lease):
    """Each `run` holds its own autocommit connection to `conninfo`, apart from the app's pool, since a held lock pins
    its connection. It campaigns with `pg_try_advisory_lock` every `interval` seconds; while held, a `SELECT 1` every
    `interval` (timing out after `interval`) checks the session is alive, and a failed one cancels the body.

    One guarantee is weaker than `EtcdLease`'s: when the server ends the session first (a restart, a terminated
    backend), the lock is free at once, so another process may take it and start its body up to about `interval`
    before this one's keepalive notices and cancels its own. There is no notion of a site, so `run_on_site` is `run`."""

    def __init__(self, conninfo: str, interval: float = 2.0, holder: str | None = None) -> None:
        self._conninfo = conninfo
        self._interval = interval
        self._holder = holder or socket.gethostname()

    async def run(self, name: str, body: Body) -> None:
        streak = Streak()
        conn: _Conn | None = None
        try:
            while True:
                conn = await self._campaign(conn, name, streak)
                streak.reset()
                if not await self._hold(conn, name, body):
                    await conn.close()
                    conn = None
                await asyncio.sleep(self._interval)
        finally:
            if conn is not None:
                await conn.close()

    async def _campaign(self, conn: _Conn | None, name: str, streak: Streak) -> _Conn:
        """Wait until a session of this `run` holds the lock; that session's connection. Cancelled mid-call, the server
        may already have granted the lock, so the connection is closed, which ends the session and frees it."""
        try:
            while True:
                try:
                    if conn is None or conn.closed:
                        conn = await asyncio.wait_for(self._connect(), max(self._interval, 2.0))
                    if await self._try_lock(conn, name):
                        return conn
                    streak.once("lease.held_elsewhere", name=name, holder=self._holder)
                except _FAILURES as e:
                    streak.once("lease.db_unreachable", name=name, holder=self._holder, error=type(e).__name__)
                    if conn is not None:
                        await conn.close()
                    conn = None
                await asyncio.sleep(self._interval)
        except asyncio.CancelledError:
            if conn is not None:
                await conn.close()
            raise

    async def _connect(self) -> _Conn:
        return await AsyncConnection.connect(self._conninfo, autocommit=True)

    async def _try_lock(self, conn: _Conn, name: str) -> bool:
        cur = await asyncio.wait_for(conn.execute(
            "SELECT pg_try_advisory_lock(hashtextextended(%s, 0))", (PREFIX + name,)), self._interval)
        row = await cur.fetchone()
        return row is not None and row[0] is True

    async def _hold(self, conn: _Conn, name: str, body: Body) -> bool:
        """Run the body while the lock holds; True when the lock was released and the session can campaign again."""
        logs.info(log, "lease.taken", name=name, holder=self._holder)
        task = asyncio.create_task(body())
        try:
            reason = await self._keep(conn, task)
        except asyncio.CancelledError:
            await self._stop(task, name)
            await self._release(conn, name, "stopped")
            raise
        if task.done():
            log_outcome(task, name, holder=self._holder)
            return await self._release(conn, name, reason)
        await self._stop(task, name)
        logs.warning(log, "lease.lost", name=name, holder=self._holder, reason=reason)
        return False

    async def _keep(self, conn: _Conn, task: asyncio.Task[None]) -> str:
        """Check the session until the body finishes or the session fails; which of those happened."""
        while True:
            await asyncio.wait({task}, timeout=self._interval)
            if task.done():
                return outcome(task)
            try:
                await asyncio.wait_for(conn.execute("SELECT 1"), self._interval)
            except TimeoutError:
                return "keepalive_timeout"
            except _FAILURES:
                return "keepalive_failed"

    async def _stop(self, task: asyncio.Task[None], name: str) -> None:
        task.cancel()
        await asyncio.wait({task}, timeout=self._interval)
        if not task.done():
            logs.error(log, "lease.body_overran", name=name, holder=self._holder)

    async def _release(self, conn: _Conn, name: str, reason: str) -> bool:
        """Unlock; False when that failed, and closing the connection must end the session (and its lock) instead."""
        logs.info(log, "lease.released", name=name, holder=self._holder, reason=reason)
        try:
            await asyncio.wait_for(conn.execute(
                "SELECT pg_advisory_unlock(hashtextextended(%s, 0))", (PREFIX + name,)), self._interval)
        except _FAILURES as e:
            logs.warning(log, "lease.unlock_failed", name=name, holder=self._holder, error=type(e).__name__)
            return False
        return True

