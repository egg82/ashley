"""Connections on a real database (`PostgresConnections`): sealing bound to household and kind on the stored row,
isolation between households, replacement, removal, `answered`."""

import asyncio
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import psycopg
import pytest
from ashley.connections.connections import Connections, ConnectionsUnavailable
from ashley.connections.postgres import PostgresConnections
from ashley.connections.sealing import Sealer
from ashley.db.pool import PoolDatabase
from ashley.people import admin
from contract.conversations_support import scalar
from connection_legacy_support import opened_of, put_of, remove_of


pytestmark = pytest.mark.usefixtures("connection_kinds_wired")

SECRET = "the-households-test-key"
BASE = "https://money.test"
KEY = os.urandom(32)


@asynccontextmanager
async def on(url: str, key: bytes = KEY) -> AsyncGenerator[Connections]:
    database = PoolDatabase(url)
    await database.open()
    try:
        yield PostgresConnections(database, Sealer({1: key}, current=1))
    finally:
        await database.close()


def seed(url: str) -> tuple[int, int, int, int]:
    with psycopg.connect(url) as conn:
        one, two = admin.add_household(conn, "one", "UTC"), admin.add_household(conn, "two", "UTC")
        return one, admin.add_person(conn, one, "Alana"), two, admin.add_person(conn, two, "Kim")


def test_put_opens_and_lists_without_the_secret(db_url: str) -> None:
    one, alana, _, _ = seed(db_url)

    async def go() -> None:
        async with on(db_url) as c:
            assert c.can_open()
            put = await put_of(c, one, "sure", BASE, SECRET, alana)
            assert await c.of_household(one) == (put,)
            opened = await opened_of(c, one, "sure")
            assert opened is not None and opened.secret == SECRET and opened.connection == put
            assert SECRET not in repr(opened) and SECRET not in repr(put)

    asyncio.run(go())
    stored = bytes(scalar(db_url, "SELECT secret FROM connections"))
    assert SECRET.encode() not in stored


def test_a_household_sees_only_its_own(db_url: str) -> None:
    one, alana, two, kim = seed(db_url)

    async def go() -> None:
        async with on(db_url) as c:
            await put_of(c, one, "sure", BASE, "one-secret", alana)
            assert await c.of_household(two) == () and await opened_of(c, two, "sure") is None
            await put_of(c, two, "sure", "https://two.test", "two-secret", kim)
            a, b = await opened_of(c, one, "sure"), await opened_of(c, two, "sure")
            assert a is not None and b is not None and (a.secret, b.secret) == ("one-secret", "two-secret")
            assert await remove_of(c, two, "sure") is True
            assert await opened_of(c, one, "sure") is not None

    asyncio.run(go())


def test_a_second_put_replaces_it(db_url: str) -> None:
    one, alana, _, _ = seed(db_url)

    async def go() -> None:
        async with on(db_url) as c:
            await put_of(c, one, "sure", BASE, "first", alana)
            await put_of(c, one, "sure", "https://new.test", "second", alana)
            assert len(await c.of_household(one)) == 1
            opened = await opened_of(c, one, "sure")
            assert opened is not None and (opened.secret, opened.connection.base_url) == ("second", "https://new.test")

    asyncio.run(go())
    assert scalar(db_url, "SELECT count(*) FROM connections") == 1


def test_a_person_of_another_household_cannot_be_the_adder(db_url: str) -> None:
    one, _, _, kim = seed(db_url)

    async def go() -> None:
        async with on(db_url) as c:
            with pytest.raises(ValueError):
                await put_of(c, one, "sure", BASE, SECRET, kim)
            assert await c.of_household(one) == ()

    asyncio.run(go())
    assert scalar(db_url, "SELECT count(*) FROM connections") == 0


def test_remove_is_true_once(db_url: str) -> None:
    one, alana, _, _ = seed(db_url)

    async def go() -> None:
        async with on(db_url) as c:
            assert await remove_of(c, one, "sure") is False
            await put_of(c, one, "sure", BASE, SECRET, alana)
            assert await remove_of(c, one, "sure") is True
            assert await remove_of(c, one, "sure") is False
            assert await opened_of(c, one, "sure") is None

    asyncio.run(go())


def test_answered_moves_checked_at_forward_only_that_connection(db_url: str) -> None:
    one, alana, two, kim = seed(db_url)

    async def go() -> None:
        async with on(db_url) as c:
            a = await put_of(c, one, "sure", BASE, SECRET, alana)
            b = await put_of(c, two, "sure", BASE, SECRET, kim)
            await asyncio.sleep(0.05)
            await c.answered(a.id)
            (a2,), (b2,) = await c.of_household(one), await c.of_household(two)
            assert a2.checked_at > a.checked_at and a2.added_at == a.added_at and b2.checked_at == b.checked_at

    asyncio.run(go())



def test_a_sealed_value_moved_to_another_household_does_not_open(db_url: str) -> None:
    one, alana, two, _ = seed(db_url)

    async def put() -> None:
        async with on(db_url) as c:
            await put_of(c, one, "sure", BASE, SECRET, alana)

    asyncio.run(put())
    with psycopg.connect(db_url) as conn:
        conn.execute("UPDATE connections SET household_id = %s, added_by = NULL", (two,))

    async def read() -> None:
        async with on(db_url) as c:
            with pytest.raises(ConnectionsUnavailable):
                await opened_of(c, two, "sure")
            assert await opened_of(c, one, "sure") is None

    asyncio.run(read())


def test_a_secret_swapped_between_households_rows_does_not_open_for_either(db_url: str) -> None:
    one, alana, two, kim = seed(db_url)

    async def put() -> None:
        async with on(db_url) as c:
            await put_of(c, one, "sure", BASE, "one-secret", alana)
            await put_of(c, two, "sure", BASE, "two-secret", kim)

    asyncio.run(put())
    with psycopg.connect(db_url) as conn:
        a, b = (bytes(scalar(db_url, "SELECT secret FROM connections WHERE household_id = %d" % h)) for h in (one, two))
        conn.execute("UPDATE connections SET secret = %s WHERE household_id = %s", (b, one))
        conn.execute("UPDATE connections SET secret = %s WHERE household_id = %s", (a, two))

    async def read() -> None:
        async with on(db_url) as c:
            for h in (one, two):
                with pytest.raises(ConnectionsUnavailable):
                    await opened_of(c, h, "sure")

    asyncio.run(read())


def test_another_key_cannot_open_what_was_stored(db_url: str) -> None:
    one, alana, _, _ = seed(db_url)

    async def put() -> None:
        async with on(db_url) as c:
            await put_of(c, one, "sure", BASE, SECRET, alana)

    asyncio.run(put())

    async def read() -> None:
        async with on(db_url, os.urandom(32)) as c:
            with pytest.raises(ConnectionsUnavailable):
                await opened_of(c, one, "sure")
            assert len(await c.of_household(one)) == 1

    asyncio.run(read())
