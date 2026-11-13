"""Connections in Postgres (`connections.postgres.PostgresConnections`) on a real database: a put is listed without
its secret and opens with it; the row holds only the sealed form; a second put replaces the first in place; a person
of another household writes nothing; another household sees none of it; a remove is once; `answered` moves
`checked_at`; a secret moved to another household's row, or read under another key, does not open; the database
gone is ConnectionsUnavailable."""

import asyncio
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import psycopg
import pytest
from ashley.connections.connections import Connections, ConnectionsUnavailable
from ashley.connections.postgres import PostgresConnections
from ashley.connections.sealing import VERSION, Sealer
from ashley.db.pool import PoolDatabase
from ashley.people import admin
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import scalar
from connection_legacy_support import opened_of, put_of, remove_of


pytestmark = pytest.mark.usefixtures("connection_kinds_wired")

KEY = os.urandom(32)
SECRET = "the-households-test-key"
BASE = "https://money.test"


@asynccontextmanager
async def connections_on(url: str, key: bytes = KEY, connect_timeout_s: float = 5.0) -> AsyncGenerator[Connections]:
    database = PoolDatabase(url, connect_timeout_s=connect_timeout_s)
    await database.open()
    try:
        yield PostgresConnections(database, Sealer({VERSION: key}))
    finally:
        await database.close()


def homes(url: str) -> tuple[int, int, int, int]:
    """Two households, a person in each."""
    with psycopg.connect(url) as conn:
        one, two = admin.add_household(conn, "one", "America/Denver"), admin.add_household(conn, "two", "UTC")
        return one, admin.add_person(conn, one, "Alana"), two, admin.add_person(conn, two, "Kim")


def test_a_put_is_listed_without_its_secret_and_opens_with_it(db_url: str) -> None:
    one, alana, two, _ = homes(db_url)

    async def scenario() -> None:
        async with connections_on(db_url) as connections:
            put = await put_of(connections, one, "sure", BASE, SECRET, alana)
            assert (put.household_id, put.kind, put.base_url, put.added_by) == (one, "sure", BASE, alana)
            assert await connections.of_household(one) == (put,)
            opened = await opened_of(connections, one, "sure")
            assert opened is not None and opened.secret == SECRET and opened.connection == put
            assert SECRET not in repr(opened)
            assert await connections.of_household(two) == ()
            assert await opened_of(connections, two, "sure") is None

    asyncio.run(scenario())
    stored = bytes(scalar(db_url, "SELECT secret FROM connections"))
    assert stored[0] == VERSION and SECRET.encode() not in stored


def test_a_second_put_replaces_the_first(db_url: str) -> None:
    one, alana, _, _ = homes(db_url)
    with psycopg.connect(db_url) as conn:
        sam = admin.add_person(conn, one, "Sam")

    async def scenario() -> None:
        async with connections_on(db_url) as connections:
            first = await put_of(connections, one, "sure", BASE, SECRET, alana)
            second = await put_of(connections, one, "sure", BASE + "/sub", "a-newer-key", sam)
            assert second.id == first.id and second.added_by == sam and second.base_url == BASE + "/sub"
            assert second.added_at >= first.added_at
            opened = await opened_of(connections, one, "sure")
            assert opened is not None and opened.secret == "a-newer-key"

    asyncio.run(scenario())
    assert scalar(db_url, "SELECT count(*) FROM connections") == 1


def test_a_person_of_another_household_writes_nothing(db_url: str) -> None:
    one, _, _, kim = homes(db_url)

    async def scenario() -> None:
        async with connections_on(db_url) as connections:
            with pytest.raises(ValueError):
                await put_of(connections, one, "sure", BASE, SECRET, kim)

    asyncio.run(scenario())
    assert scalar(db_url, "SELECT count(*) FROM connections") == 0


def test_a_remove_is_once_and_answered_moves_checked_at(db_url: str) -> None:
    one, alana, _, _ = homes(db_url)

    async def scenario() -> None:
        async with connections_on(db_url) as connections:
            put = await put_of(connections, one, "sure", BASE, SECRET, alana)
            await asyncio.sleep(0.01)
            await connections.answered(put.id)
            (now,) = await connections.of_household(one)
            assert now.checked_at > put.checked_at and now.added_at == put.added_at
            assert await remove_of(connections, one, "sure") is True
            assert await remove_of(connections, one, "sure") is False
            assert await opened_of(connections, one, "sure") is None

    asyncio.run(scenario())


def test_a_secret_moved_to_another_households_row_does_not_open(db_url: str) -> None:
    one, alana, two, kim = homes(db_url)

    async def scenario() -> None:
        async with connections_on(db_url) as connections:
            await put_of(connections, one, "sure", BASE, SECRET, alana)
            await put_of(connections, two, "sure", BASE, "kims-key", kim)

    asyncio.run(scenario())
    with psycopg.connect(db_url) as conn:
        conn.execute("UPDATE connections SET secret = (SELECT secret FROM connections WHERE household_id = %s) "
                     "WHERE household_id = %s", (one, two))

    async def read() -> None:
        async with connections_on(db_url) as connections:
            with pytest.raises(ConnectionsUnavailable):
                await opened_of(connections, two, "sure")

    asyncio.run(read())


def test_another_key_does_not_open_it(db_url: str) -> None:
    one, alana, _, _ = homes(db_url)

    async def scenario() -> None:
        async with connections_on(db_url) as connections:
            await put_of(connections, one, "sure", BASE, SECRET, alana)
        async with connections_on(db_url, os.urandom(32)) as other:
            with pytest.raises(ConnectionsUnavailable):
                await opened_of(other, one, "sure")
            assert len(await other.of_household(one)) == 1

    asyncio.run(scenario())


def test_no_database_is_unavailable() -> None:
    async def scenario() -> None:
        database = PoolDatabase("postgresql://nobody@127.0.0.1:1/none?connect_timeout=1")
        connections = PostgresConnections(database, Sealer({VERSION: KEY}))
        with pytest.raises(ConnectionsUnavailable):
            await connections.of_household(1)

    asyncio.run(scenario())


HA = "http://ha.test:8123"


def test_a_household_holds_a_home_assistant_beside_its_sure(db_url: str) -> None:
    one, alana, _, _ = homes(db_url)

    async def scenario() -> None:
        async with connections_on(db_url) as connections:
            await put_of(connections, one, "sure", BASE, SECRET, alana)
            await put_of(connections, one, "home_assistant", HA, "ha-token", alana)
            assert [c.kind for c in await connections.of_household(one)] == ["home_assistant", "sure"]
            opened = await opened_of(connections, one, "home_assistant")
            assert opened is not None and (opened.connection.base_url, opened.secret) == (HA, "ha-token")

    asyncio.run(scenario())


def test_a_seed_is_written_once_with_no_one_as_its_adder_and_never_over_a_row(db_url: str) -> None:
    one, alana, _, _ = homes(db_url)

    async def scenario() -> None:
        async with connections_on(db_url) as connections:
            seeded = await connections.seed(one, "home_assistant", HA, "env-token")
            assert seeded is not None and (seeded.household_id, seeded.kind, seeded.added_by) == (
                one, "home_assistant", None)
            assert await connections.seed(one, "home_assistant", HA + "/other", "another") is None
            opened = await opened_of(connections, one, "home_assistant")
            assert opened is not None and (opened.connection.base_url, opened.secret) == (HA, "env-token")
            await put_of(connections, one, "home_assistant", HA, "alanas-token", alana)
            assert await connections.seed(one, "home_assistant", HA, "env-token") is None
            kept = await opened_of(connections, one, "home_assistant")
            assert kept is not None and kept.secret == "alanas-token" and kept.connection.added_by == alana

    asyncio.run(scenario())


def test_a_seed_for_no_such_household_writes_nothing(db_url: str) -> None:
    async def scenario() -> None:
        async with connections_on(db_url) as connections:
            assert await connections.seed(987654, "home_assistant", HA, "env-token") is None

    asyncio.run(scenario())
    assert scalar(db_url, "SELECT count(*) FROM connections") == 0
