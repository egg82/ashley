"""Provider keys as the first household's connections, on a real database: the env's keys are seeded once, by one of
several pods seeding at once, and never over a row; the key in force is the row's where one exists and the env's
elsewhere, so a changed env key is ignored while a row stands and comes back when the row is removed; another
household's rows and a person's own are never read; no `CONNECTIONS_KEY` means the env's keys; a database that cannot
be reached, or a stored key sealed under another key, is KeysUnavailable rather than the env's key."""

import asyncio
import os

import psycopg
import pytest
from ashley.connections.connections import NullConnections
from ashley.connections.kinds import FIRST_HOUSEHOLD
from ashley.inference.key_seed import Outcome, seed_from_env
from ashley.inference.kinds import ANTHROPIC, KEYED
from ashley.inference.provider_keys import ConnectionProviderKeys, KeyInForce, KeysUnavailable
from ashley.people import admin
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import scalar
from connection_legacy_support import put_of, remove_of
from test_connections_postgres import connections_on

pytestmark = pytest.mark.usefixtures("connection_kinds_wired")

KINDS = [k.kind.name for k in KEYED]


def households(url: str) -> tuple[int, int, int, int]:
    """The first household and another, a person in each."""
    with psycopg.connect(url) as conn:
        one, two = admin.add_household(conn, "one", "UTC"), admin.add_household(conn, "two", "UTC")
        assert one == FIRST_HOUSEHOLD
        return one, admin.add_person(conn, one, "Alana"), two, admin.add_person(conn, two, "Kim")


def secrets(keys: dict[str, KeyInForce]) -> dict[str, tuple[str, bool]]:
    """Each kind's key and whether it came from a row."""
    return {kind: (key.secret, key.connection_id is not None) for kind, key in keys.items()}


def test_several_pods_seeding_at_once_write_one_row_per_kind(db_url: str) -> None:
    households(db_url)
    env = {"anthropic": "sk-ant", "openai": "sk-oai", "gemini": "", "elevenlabs": ""}

    async def scenario() -> list[dict[str, Outcome]]:
        async with connections_on(db_url) as connections:
            return list(await asyncio.gather(*(seed_from_env(connections, KEYED, env) for _ in range(6))))
    outcomes = asyncio.run(scenario())
    assert all(set(o) == {"anthropic", "openai"} for o in outcomes)
    assert sorted(o["anthropic"] for o in outcomes) == ["kept"] * 5 + ["seeded"]
    rows = scalar(db_url, "SELECT count(*) FROM connections WHERE household_id = %s AND added_by IS NULL",
                  (FIRST_HOUSEHOLD,))
    assert rows == 2


def test_a_row_wins_over_the_env_and_the_env_comes_back_when_it_is_removed(db_url: str) -> None:
    one, alana, two, kim = households(db_url)

    async def scenario() -> None:
        async with connections_on(db_url) as connections:
            env = {"anthropic": "sk-env-first"}
            assert await seed_from_env(connections, KEYED, env) == {"anthropic": "seeded"}
            await put_of(connections, one, "anthropic", ANTHROPIC.address, "sk-rotated", alana)
            await put_of(connections, two, "openai", "https://api.openai.com", "sk-other-household", kim)
            changed = {"anthropic": "sk-env-changed", "openai": ""}
            assert await seed_from_env(connections, KEYED, changed) == {"anthropic": "kept"}
            keys = ConnectionProviderKeys(lambda: connections, KINDS, changed)
            assert secrets(dict(await keys.in_force())) == {"anthropic": ("sk-rotated", True)}
            await remove_of(connections, one, "anthropic")
            assert secrets(dict(await keys.in_force())) == {"anthropic": ("sk-env-changed", False)}
    asyncio.run(scenario())


def test_without_the_connections_key_the_envs_keys_are_in_force_and_nothing_is_seeded() -> None:
    env = {"anthropic": "sk-ant", "openai": "", "elsewhere": "sk-not-a-kind"}
    keys = ConnectionProviderKeys(NullConnections, KINDS, env)
    assert secrets(dict(asyncio.run(keys.in_force()))) == {"anthropic": ("sk-ant", False)}
    assert asyncio.run(seed_from_env(NullConnections(), KEYED, env)) == {"anthropic": "no_key"}


def test_an_unreachable_database_is_unavailable_not_the_envs_key() -> None:
    async def scenario() -> None:
        async with connections_on("postgresql://nobody@127.0.0.1:1/none?connect_timeout=1") as connections:
            with pytest.raises(KeysUnavailable):
                await ConnectionProviderKeys(lambda: connections, KINDS, {"anthropic": "sk-env"}).in_force()
            assert await seed_from_env(connections, KEYED, {"anthropic": "sk-env"}) == {"anthropic": "unavailable"}
    asyncio.run(scenario())


def test_a_key_sealed_under_another_connections_key_is_unavailable(db_url: str) -> None:
    households(db_url)

    async def scenario() -> None:
        async with connections_on(db_url) as connections:
            await seed_from_env(connections, KEYED, {"gemini": "sk-gem"})
        async with connections_on(db_url, os.urandom(32)) as other:
            with pytest.raises(KeysUnavailable):
                await ConnectionProviderKeys(lambda: other, KINDS, {}).in_force()
    asyncio.run(scenario())
