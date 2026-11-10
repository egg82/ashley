"""`seed_from_env` and `Connections.seed`: insert-if-absent, never over a person's row, never raises, one row from
concurrent seeds (in memory and on a real database)."""

import asyncio
from collections.abc import AsyncGenerator, Coroutine
from contextlib import asynccontextmanager
from typing import Any

import psycopg
import pytest
from ashley.connections.connections import Connections
from ashley.connections.postgres import PostgresConnections
from ashley.connections.sealing import Sealer
from ashley.db.pool import PoolDatabase
from ashley.home_assistant.seed import seed_from_env
from ashley.people import admin
from contract.conversations_support import scalar
from hha_blind_support import A_TOKEN, A_URL, ENV, HeldConnections
from connection_legacy_support import opened_of, put_of


pytestmark = pytest.mark.usefixtures("connection_kinds_wired")

KEY = bytes(range(32))


def run(coro: Coroutine[Any, Any, None]) -> None:
    asyncio.run(asyncio.wait_for(coro, 20))


@asynccontextmanager
async def on(url: str) -> AsyncGenerator[Connections]:
    database = PoolDatabase(url)
    await database.open()
    try:
        yield PostgresConnections(database, Sealer({1: KEY}, current=1))
    finally:
        await database.close()


def households(url: str) -> tuple[int, int, int]:
    with psycopg.connect(url) as conn:
        one, two = admin.add_household(conn, "one", "UTC"), admin.add_household(conn, "two", "UTC")
        return one, admin.add_person(conn, one, "Alana"), two


def test_it_seeds_household_ones_row_and_the_row_opens_with_the_env() -> None:
    held = HeldConnections()

    async def go() -> None:
        await seed_from_env(held, *ENV)
        opened = await opened_of(held, 1, "home_assistant")
        assert opened is not None and (opened.connection.base_url, opened.secret) == ENV

    run(go())


def test_it_leaves_a_row_that_is_there() -> None:
    held = HeldConnections()
    held.connect(1, A_URL, A_TOKEN)

    async def go() -> None:
        await seed_from_env(held, *ENV)
        opened = await opened_of(held, 1, "home_assistant")
        assert opened is not None and (opened.connection.base_url, opened.secret) == (A_URL, A_TOKEN)

    run(go())


def test_the_outcomes_tell_seeded_from_kept() -> None:
    held = HeldConnections()

    async def go() -> None:
        first, second = await seed_from_env(held, *ENV), await seed_from_env(held, *ENV)
        assert (first, second) == ("seeded", "kept")

    run(go())


def test_connections_it_cannot_reach_is_an_outcome_not_an_error() -> None:
    held = HeldConnections(down=True)

    async def go() -> None:
        assert await seed_from_env(held, *ENV) == "unavailable"

    run(go())


def test_a_refused_seed_is_an_outcome_not_an_error() -> None:
    held = HeldConnections(seed_fails=True)

    async def go() -> None:
        assert await seed_from_env(held, *ENV) == "unavailable"
        assert held.held == {}

    run(go())


def test_without_the_key_nothing_is_seeded() -> None:
    class NoKey(HeldConnections):
        def can_open(self) -> bool:
            return False

    held = NoKey()

    async def go() -> None:
        assert await seed_from_env(held, *ENV) == "no_key"
        assert held.held == {}

    run(go())


@pytest.mark.parametrize("base", ["", "not a url", "ftp://x.test", "http://u:p@x.test"])
def test_an_address_that_is_no_address_is_an_outcome_and_stores_nothing(base: str) -> None:
    held = HeldConnections()

    async def go() -> None:
        assert await seed_from_env(held, base, "token") == "bad_url"
        assert held.held == {}

    run(go())


def test_seed_inserts_if_absent_and_keeps_the_first_on_a_real_database(db_url: str) -> None:
    one, _, two = households(db_url)

    async def go() -> None:
        async with on(db_url) as c:
            made = await c.seed(one, "home_assistant", A_URL, "first")
            assert made is not None and made.household_id == one and made.kind == "home_assistant"
            assert made.added_by is None
            assert await c.seed(one, "home_assistant", "http://other.test", "second") is None
            opened = await opened_of(c, one, "home_assistant")
            assert opened is not None and (opened.secret, opened.connection.base_url) == ("first", A_URL)
            assert await c.seed(two, "home_assistant", A_URL, "twos") is not None
            assert await c.seed(one, "sure", "https://money.test", "sure-key") is not None

    run(go())
    assert scalar(db_url, "SELECT count(*) FROM connections") == 3


def test_seed_never_overwrites_a_persons_row(db_url: str) -> None:
    one, alana, _ = households(db_url)

    async def go() -> None:
        async with on(db_url) as c:
            await put_of(c, one, "home_assistant", A_URL, "persons", alana)
            assert await c.seed(one, "home_assistant", "http://env.test", "env") is None
            opened = await opened_of(c, one, "home_assistant")
            assert opened is not None and (opened.secret, opened.connection.added_by) == ("persons", alana)

    run(go())


def test_a_person_replaces_a_seeded_row(db_url: str) -> None:
    one, alana, _ = households(db_url)

    async def go() -> None:
        async with on(db_url) as c:
            await c.seed(one, "home_assistant", "http://env.test", "env")
            await put_of(c, one, "home_assistant", A_URL, "persons", alana)
            opened = await opened_of(c, one, "home_assistant")
            assert opened is not None and (opened.secret, opened.connection.added_by) == ("persons", alana)

    run(go())


def test_concurrent_seeds_make_one_row_and_one_winner(db_url: str) -> None:
    one, _, _ = households(db_url)

    async def go() -> None:
        async with on(db_url) as c, on(db_url) as d:
            made = await asyncio.gather(*[(c if i % 2 else d).seed(one, "home_assistant", f"http://h{i}.test", f"s{i}")
                                          for i in range(12)])
            assert len([m for m in made if m is not None]) == 1
            opened = await opened_of(c, one, "home_assistant")
            winner = next(m for m in made if m is not None)
            assert opened is not None and opened.connection.base_url == winner.base_url
            assert opened.secret == "s" + winner.base_url.removeprefix("http://h").removesuffix(".test")

    run(go())
    assert scalar(db_url, "SELECT count(*) FROM connections") == 1


def test_concurrent_seed_from_env_over_pods_leaves_one_row(db_url: str) -> None:
    _, _, _ = households(db_url)

    async def go() -> None:
        async with on(db_url) as c:
            outcomes = await asyncio.gather(*[seed_from_env(c, *ENV) for _ in range(10)])
            assert sorted(set(outcomes)) == ["kept", "seeded"] and outcomes.count("seeded") == 1

    run(go())
    assert scalar(db_url, "SELECT count(*) FROM connections") == 1


def test_a_seeded_secret_is_sealed_at_rest(db_url: str) -> None:
    one, _, _ = households(db_url)

    async def go() -> None:
        async with on(db_url) as c:
            await c.seed(one, "home_assistant", A_URL, "plain-token-value")

    run(go())
    assert b"plain-token-value" not in bytes(scalar(db_url, "SELECT secret FROM connections"))


def test_seed_with_the_table_unreadable_is_unavailable_for_the_caller(db_url: str) -> None:
    _, _, _ = households(db_url)

    async def go() -> None:
        async with on(db_url) as c:
            with psycopg.connect(db_url, autocommit=True) as conn:
                conn.execute("ALTER TABLE connections RENAME TO connections_gone")
            assert await seed_from_env(c, *ENV) == "unavailable"

    run(go())


def test_seeding_a_household_that_does_not_exist_stores_nothing_and_does_not_raise(db_url: str) -> None:
    async def go() -> None:
        async with on(db_url) as c:
            assert await c.seed(999, "home_assistant", A_URL, "t") is None
            assert await seed_from_env(c, *ENV, household_id=999) in ("kept", "unavailable")

    run(go())
    assert scalar(db_url, "SELECT count(*) FROM connections") == 0
