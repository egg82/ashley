"""`key_seed.seed_from_env` on a real database: each non-empty env key becomes the first household's connection of its
kind at the kind's fixed address, with no adder and an empty label, sealed so it opens to the env's key; it is idempotent,
never overwrites a stored row, writes exactly one row when many pods seed at once, and reports `kept` for a missing first
household, `no_key` without the sealing key and `unavailable` for a database that is away, never raising; kinds with no
env key are absent from the result; the log carries outcomes and never a key."""

import asyncio
import logging

import psycopg
import pytest
from ashley.connections.connections import NullConnections
from ashley.connections.kinds import FIRST_HOUSEHOLD
from ashley.connections.postgres import PostgresConnections
from ashley.connections.sealing import VERSION, Sealer
from ashley.db.pool import PoolDatabase
from ashley.inference.keyed import KeyedProvider
from ashley.inference.key_seed import Outcome, seed_from_env
from ashley.inference.provider_keys import ConnectionProviderKeys
from ashley.people import admin
from contract.conversations_support import scalar
from pkb_support import A, B, C, SEALING_KEY, Recorder, Unreachable, connections_on, keyed

pytestmark = pytest.mark.usefixtures("provider_kinds")
ENV = {A: "sk-env-alpha-1111", B: "sk-env-beta-2222", C: ""}
PODS = 6


def providers() -> list[KeyedProvider]:
    recorder = Recorder()
    return [keyed(recorder, k) for k in (A, B, C)]


def first_household(url: str) -> int:
    with psycopg.connect(url) as conn:
        made = admin.add_household(conn, "one", "UTC")
    assert made == FIRST_HOUSEHOLD
    return made


def rows(url: str) -> list[tuple[str, int | None, str, str, int | None]]:
    with psycopg.connect(url) as conn:
        return conn.execute("SELECT kind, household_id, label, base_url, added_by FROM connections "
                            "ORDER BY kind").fetchall()


def test_each_env_key_becomes_the_first_households_connection_and_empty_ones_are_absent(db_url: str) -> None:
    first_household(db_url)

    async def scenario() -> None:
        async with connections_on(db_url) as connections:
            got = await seed_from_env(connections, providers(), ENV)
            assert got == {A: "seeded", B: "seeded"}, "C's env key is empty, so it is not in the result"
            keys = await ConnectionProviderKeys(lambda: connections, (A, B, C), {}).in_force()
            assert {k: v.secret for k, v in keys.items()} == {A: ENV[A], B: ENV[B]}
            assert all(v.connection_id is not None for v in keys.values())

    asyncio.run(scenario())
    assert rows(db_url) == [(A, FIRST_HOUSEHOLD, "", f"https://api.{A}.test", None),
                            (B, FIRST_HOUSEHOLD, "", f"https://api.{B}.test", None)]
    stored = bytes(scalar(db_url, "SELECT secret FROM connections WHERE kind = %s", (A,)))
    assert stored[0] == VERSION and ENV[A].encode() not in stored


def test_a_kind_missing_from_the_env_is_absent_from_the_result(db_url: str) -> None:
    first_household(db_url)

    async def scenario() -> None:
        async with connections_on(db_url) as connections:
            assert await seed_from_env(connections, providers(), {A: ENV[A]}) == {A: "seeded"}
            assert await seed_from_env(connections, providers(), {}) == {}

    asyncio.run(scenario())
    assert len(rows(db_url)) == 1


def test_seeding_again_is_kept_and_a_changed_env_key_never_overwrites_the_stored_one(db_url: str) -> None:
    first_household(db_url)

    async def scenario() -> None:
        async with connections_on(db_url) as connections:
            await seed_from_env(connections, providers(), ENV)
            again = await seed_from_env(connections, providers(), {A: "sk-env-changed-9999", B: ENV[B]})
            assert again == {A: "kept", B: "kept"}
            keys = await ConnectionProviderKeys(lambda: connections, (A,), {}).in_force()
            assert keys[A].secret == ENV[A]

    asyncio.run(scenario())
    assert len(rows(db_url)) == 2


def test_a_row_a_person_added_is_kept(db_url: str) -> None:
    first = first_household(db_url)
    with psycopg.connect(db_url) as conn:
        alana = admin.add_person(conn, first, "Alana")

    async def scenario() -> None:
        async with connections_on(db_url) as connections:
            await connections.add(first, A, "", f"https://api.{A}.test", "sk-typed-in-by-a-person", alana)
            assert await seed_from_env(connections, providers(), ENV) == {A: "kept", B: "seeded"}
            keys = await ConnectionProviderKeys(lambda: connections, (A,), {}).in_force()
            assert keys[A].secret == "sk-typed-in-by-a-person"

    asyncio.run(scenario())


def test_many_pods_seeding_at_once_write_one_row_per_kind_and_the_rest_see_kept(db_url: str) -> None:
    first_household(db_url)

    async def scenario() -> list[dict[str, Outcome]]:
        databases = [PoolDatabase(db_url) for _ in range(PODS)]
        for d in databases:
            await d.open()
        try:
            pods = [PostgresConnections(d, Sealer({VERSION: SEALING_KEY})) for d in databases]
            return list(await asyncio.gather(*(seed_from_env(p, providers(), ENV) for p in pods)))
        finally:
            for d in databases:
                await d.close()

    outcomes = asyncio.run(scenario())
    for kind in (A, B):
        mine = sorted(o[kind] for o in outcomes)
        assert mine == ["kept"] * (PODS - 1) + ["seeded"], mine
    assert [r[0] for r in rows(db_url)] == [A, B]


def test_no_first_household_is_kept_and_writes_nothing(db_url: str) -> None:
    async def scenario() -> None:
        async with connections_on(db_url) as connections:
            assert await seed_from_env(connections, providers(), ENV) == {A: "kept", B: "kept"}

    asyncio.run(scenario())
    assert rows(db_url) == []


def test_without_the_sealing_key_each_kind_with_an_env_key_is_no_key() -> None:
    assert asyncio.run(seed_from_env(NullConnections(), providers(), ENV)) == {A: "no_key", B: "no_key"}


def test_an_unreachable_database_is_unavailable_and_never_raises() -> None:
    assert asyncio.run(seed_from_env(Unreachable(), providers(), ENV)) == {A: "unavailable", B: "unavailable"}


def test_a_database_that_cannot_be_connected_to_is_unavailable() -> None:
    async def scenario() -> dict[str, str]:
        database = PoolDatabase("postgresql://nobody@127.0.0.1:1/none?connect_timeout=1")
        return dict(await seed_from_env(PostgresConnections(database, Sealer({VERSION: SEALING_KEY})), providers(), ENV))

    assert asyncio.run(scenario()) == {A: "unavailable", B: "unavailable"}


def test_the_log_names_each_kinds_outcome_and_never_a_key(db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    first_household(db_url)

    async def scenario() -> None:
        async with connections_on(db_url) as connections:
            await seed_from_env(connections, providers(), ENV)
            await seed_from_env(connections, providers(), ENV)
        await seed_from_env(Unreachable(), providers(), ENV)

    with caplog.at_level(logging.DEBUG):
        asyncio.run(scenario())
    seeds = [r for r in caplog.records if r.getMessage() == "provider_keys.seed"]
    assert len(seeds) == 6
    shown = repr([r.__dict__.get("fields") for r in seeds])
    assert all(o in shown for o in ("seeded", "kept", "unavailable"))
    everything = caplog.text + repr([r.__dict__ for r in caplog.records])
    assert not any(k in everything for k in (ENV[A], ENV[B]))
