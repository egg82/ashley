"""Helpers for the blind Conversations contract tests: a migrated database per test (cloned from one migrated template
per worker, so the migration is paid once), raw SQL to set up households and people and to age a conversation, the
service under test built from its public constructor, and logfmt parsing."""

import asyncio
import re
import uuid
from collections.abc import AsyncGenerator, Awaitable, Coroutine, Generator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import datetime
from typing import Any, get_args

import psycopg
import pytest
from ashley.conversations.conversations import Conversations
from ashley.conversations.model import Kind
from ashley.conversations.policy import Policy, Timing
from ashley.conversations.postgres import PostgresConversations
from ashley.db.database import Database, Probe
from ashley.db.migrate import migrate
from ashley.db.pool import PoolDatabase
from pg import admin_url
from psycopg import AsyncConnection, sql
from psycopg.conninfo import make_conninfo

KINDS: tuple[Kind, ...] = get_args(Kind)
FIELD = re.compile(r'(\w+)=("(?:[^"\\]|\\.)*"|\S*)')

# Each kind's thresholds a decade apart, so an implementation reading another kind's timing answers a wrong state.
POLICY = Policy({
    "command": Timing(idle_after_s=10, closed_after_s=100),
    "chat": Timing(idle_after_s=1_000, closed_after_s=10_000),
    "brainstorm": Timing(idle_after_s=100_000, closed_after_s=1_000_000),
})


def run(scenario: Coroutine[Any, Any, None], limit: float = 25.0) -> None:
    async def bounded() -> None:
        await asyncio.wait_for(scenario, limit)

    asyncio.run(bounded())


def make(database: Database, policy: Policy = POLICY) -> Conversations:
    return PostgresConversations(database, policy)


@asynccontextmanager
async def service(url: str, policy: Policy = POLICY, connect_timeout_s: float = 5.0) -> AsyncGenerator[Conversations]:
    db = PoolDatabase(url, connect_timeout_s=connect_timeout_s)
    await db.open()
    try:
        yield make(db, policy)
    finally:
        await db.close()


class TouchDatabase(Database):
    """Records every request for a connection and grants none: proof a call failed before touching the database."""

    def __init__(self) -> None:
        self.touched = 0

    async def open(self) -> None: ...

    async def close(self) -> None: ...

    async def probe(self) -> Probe:
        self.touched += 1
        return Probe(reachable=False, writable=False)

    def connection(self) -> AbstractAsyncContextManager[AsyncConnection[tuple[Any, ...]]]:
        self.touched += 1
        raise AssertionError("the database was touched")


# --- the database -----------------------------------------------------------------------------------------------


@pytest.fixture(scope="session")
def migrated_template() -> Generator[str]:
    """One migrated database per worker, the template every test's database is cloned from."""
    admin = admin_url()
    name = f"ashley_tmpl_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    try:
        migrate(make_conninfo(admin, dbname=name))
        with psycopg.connect(admin, autocommit=True) as conn:
            conn.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s", (name,))
        yield name
    finally:
        with psycopg.connect(admin, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


@pytest.fixture
def db_url(migrated_template: str) -> Generator[str]:
    """A fresh database at the head revision, dropped afterwards."""
    admin = admin_url()
    name = f"ashley_test_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {} TEMPLATE {}").format(
            sql.Identifier(name), sql.Identifier(migrated_template)))
    try:
        yield make_conninfo(admin, dbname=name)
    finally:
        with psycopg.connect(admin, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


def scalar(url: str, query: str, params: tuple[object, ...] = ()) -> Any:
    with psycopg.connect(url, autocommit=True) as conn:
        row = conn.execute(query.encode(), params).fetchone()
    assert row is not None
    return row[0]


async def ascalar(url: str, query: str, params: tuple[object, ...] = ()) -> Any:
    """`scalar` for a test that runs on an event loop: the query does not block it."""
    async with await AsyncConnection.connect(url, autocommit=True) as conn:
        row = await (await conn.execute(query.encode(), params)).fetchone()
    assert row is not None
    return row[0]


async def aexecute(url: str, query: str, params: tuple[object, ...] = ()) -> None:
    """Run one statement without blocking the event loop."""
    async with await AsyncConnection.connect(url, autocommit=True) as conn:
        await conn.execute(query.encode(), params)


def household(url: str, name: str = "home") -> int:
    return int(scalar(url, "INSERT INTO households (name) VALUES (%s) RETURNING id", (name,)))


def person(url: str, household_id: int, name: str = "someone") -> int:
    return int(scalar(url, "INSERT INTO people (household_id, name) VALUES (%s, %s) RETURNING id",
                      (household_id, name)))


def db_now(url: str) -> datetime:
    value: datetime = scalar(url, "SELECT clock_timestamp()")
    return value


def shift_back(url: str, conversation_id: int, seconds: float) -> None:
    """Move a whole conversation into the past by `seconds`: its start, its last activity and every turn, together,
    so it reads the same to an implementation whichever of them it derives its state from."""
    with psycopg.connect(url) as conn:
        gap = (f"{seconds} seconds",)
        conn.execute("UPDATE conversations SET started_at = started_at - %s::interval, "
                     "last_activity_at = last_activity_at - %s::interval WHERE id = %s",
                     (*gap, *gap, conversation_id))
        conn.execute("UPDATE turns SET at = at - %s::interval WHERE conversation_id = %s", (*gap, conversation_id))


def place_before_now(url: str, conversation_id: int, seconds: float) -> None:
    """Shift a conversation back so its last activity is `seconds` before the database's now."""
    last: datetime = scalar(url, "SELECT last_activity_at FROM conversations WHERE id = %s", (conversation_id,))
    elapsed = (db_now(url) - last).total_seconds()
    shift_back(url, conversation_id, seconds - elapsed)


def closing_first(url: str, step: Any) -> Any:
    """`step`, a model's step, wrapped so the newest conversation has closed by the time it answers."""
    async def closing(*args: Any, **kwargs: Any) -> Any:
        place_before_now(url, int(scalar(url, "SELECT max(id) FROM conversations")), 100_000)
        return await step(*args, **kwargs)
    return closing


def footprint(url: str) -> tuple[str, ...]:
    """Every stored row of every table, so a call that must write nothing can be checked."""
    return tuple(str(scalar(url, f"SELECT coalesce(string_agg(t::text, '|' ORDER BY t::text), '') FROM {table} t"))
                 for table in ("households", "people", "conversations", "conversation_participants", "turns"))


async def gather_settled(*calls: Awaitable[Any]) -> list[Any]:
    return list(await asyncio.gather(*calls, return_exceptions=True))


def events(out: str, event: str) -> list[dict[str, str]]:
    """The logfmt lines of `event`, field values unquoted."""
    lines = [{k: v.strip('"') for k, v in FIELD.findall(line)} for line in out.splitlines()]
    return [ln for ln in lines if ln.get("event") == event]


@asynccontextmanager
async def holding(url: str, lock_query: str, params: tuple[object, ...]) -> AsyncGenerator[AsyncConnection[Any]]:
    """A second connection holding the row locks `lock_query` takes, until the block exits (then it commits)."""
    async with await AsyncConnection.connect(url) as conn:
        await conn.execute(lock_query.encode(), params)
        yield conn


async def blocked_backend(url: str, timeout: float = 5.0) -> int:
    """The pid of a backend in this database waiting on a lock; fails if none waits within `timeout`. Polls the
    database's own view, so the wait is on the database, not a guess at wall-clock time."""
    async with await AsyncConnection.connect(url, autocommit=True) as conn:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while loop.time() < deadline:
            cur = await conn.execute(
                "SELECT pid FROM pg_stat_activity WHERE datname = current_database() AND wait_event_type = 'Lock' "
                "AND pid <> pg_backend_pid()")
            row = await cur.fetchone()
            if row is not None:
                return int(row[0])
            await asyncio.sleep(0.01)
    raise AssertionError("no call ever waited on the held lock, so the case was never exercised")
