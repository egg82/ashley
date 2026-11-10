"""Helpers for the Postgres lease contract tests: look at the session advisory locks from outside, take and kill them,
reach the subject without importing it at module load, and a lease that never locks (the control)."""

import asyncio
import importlib
from collections.abc import Callable
from contextlib import AsyncExitStack
from typing import Any

import psycopg
from ashley.referee.lease import Body, Lease
from lease_support import Arena, campaign, run, wait_until

KEY = "hashtextextended('ashley/singletons/' || %s, 0)"
HOLDERS = f"""SELECT pid FROM pg_locks WHERE locktype = 'advisory' AND granted AND database = (
    SELECT oid FROM pg_database WHERE datname = current_database())
    AND ((classid::bigint << 32) | objid::bigint) = {KEY} ORDER BY pid"""


def postgres_lease_class() -> type[Lease]:
    """The subject, imported on use so the controls in this suite run before it exists."""
    cls: type[Lease] = importlib.import_module("ashley.referee.postgres_lease").PostgresLease
    return cls


def subject(conninfo: str, interval: float = 0.2, holder: str | None = None) -> Lease:
    cls: Any = postgres_lease_class()
    instance: Lease = cls(conninfo, interval=interval, holder=holder)
    return instance


def holders(conninfo: str, name: str) -> list[int]:
    """Backend pids holding the session advisory lock for singleton `name`, as the server reports them."""
    with psycopg.connect(conninfo, autocommit=True) as conn:
        return [int(row[0]) for row in conn.execute(HOLDERS, (name,)).fetchall()]


def hold(conninfo: str, name: str) -> psycopg.Connection[Any]:
    """Take the lock from outside, on a connection the caller closes (or `release`s) to give it back."""
    conn = psycopg.connect(conninfo, autocommit=True)
    row = conn.execute(f"SELECT pg_try_advisory_lock({KEY})", (name,)).fetchone()
    assert row is not None and row[0], "the lock was not free to take"
    return conn


def release(conn: psycopg.Connection[Any], name: str) -> None:
    conn.execute(f"SELECT pg_advisory_unlock({KEY})", (name,))


def terminate(conninfo: str, pid: int) -> None:
    with psycopg.connect(conninfo, autocommit=True) as conn:
        row = conn.execute("SELECT pg_terminate_backend(%s)", (pid,)).fetchone()
        assert row is not None and row[0], "the backend was not terminated"


class UnlockedLease(Lease):
    """Runs every body at once with no lock: what the exclusion check must be able to tell from a real lease."""

    async def run(self, name: str, body: Body) -> None:
        await body()


def max_concurrent_bodies(make: Callable[[str], Lease], name: str, count: int = 3) -> int:
    """`count` leases campaign for `name`; the most bodies seen running at once after they have had time to start."""
    arena = Arena()

    async def scenario() -> None:
        async with AsyncExitStack() as stack:
            for i in range(count):
                await stack.enter_async_context(campaign(make(f"h{i}"), name, arena.body(f"h{i}")))
            await wait_until(lambda: arena.starts)
            await asyncio.sleep(0.6)

    run(scenario())
    return arena.max_running
