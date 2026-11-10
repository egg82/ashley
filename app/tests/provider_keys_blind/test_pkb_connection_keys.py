"""`ConnectionProviderKeys` on a real database: a stored household-held row of the first household beats the env's key
and the env's is ignored while it exists; the env stands in where there is no row and an empty env key is no key; rows
of other kinds, other households and a person's own are never read; no `CONNECTIONS_KEY` serves the env's keys without
raising; a database that is away, or a stored key that does not open, raises `KeysUnavailable` instead of answering
with the env's keys; it follows the service the locator holds on each read."""

import asyncio
import os

import psycopg
import pytest
from ashley import services
from ashley.connections.connections import Connections, NullConnections
from ashley.connections.kinds import FIRST_HOUSEHOLD, ConnectionKinds
from ashley.connections.model import Holder
from ashley.inference.provider_keys import ConnectionProviderKeys, KeyInForce, KeysUnavailable
from ashley.people import admin
from pkb_support import A, B, C, SEALING_KEY, Unreachable, connections_on, deployment_kind

pytestmark = pytest.mark.usefixtures("provider_kinds")
ROW, ENV = "sk-row-key-1111", "sk-env-key-2222"


def households(url: str) -> tuple[int, int, int]:
    """The first household, a second, and a person of the first."""
    with psycopg.connect(url) as conn:
        first, second = admin.add_household(conn, "one", "UTC"), admin.add_household(conn, "two", "UTC")
        return first, second, admin.add_person(conn, first, "Alana")


def reader(connections: Connections, env: dict[str, str], kinds: tuple[str, ...] = (A, B)) -> ConnectionProviderKeys:
    return ConnectionProviderKeys(lambda: connections, kinds, env)


async def add(connections: Connections, household: int, kind: str, secret: str, person: int,
              holder: Holder | None = None) -> int:
    made = await connections.add(household, kind, "", f"https://api.{kind}.test", secret, person, holder)
    return made.id


def test_the_first_household_is_household_one() -> None:
    assert FIRST_HOUSEHOLD == 1


@pytest.mark.parametrize("row,env,expected", [
    (True, True, (ROW, False)), (True, False, (ROW, False)), (False, True, (ENV, True)), (False, False, None)])
def test_a_row_wins_over_the_env_and_the_env_stands_in_without_one(
        db_url: str, row: bool, env: bool, expected: tuple[str, bool] | None) -> None:
    first, _, alana = households(db_url)
    assert first == FIRST_HOUSEHOLD

    async def scenario() -> None:
        async with connections_on(db_url) as connections:
            stored = await add(connections, first, A, ROW, alana) if row else None
            got = await reader(connections, {A: ENV} if env else {}).in_force()
            if expected is None:
                assert A not in got
                return
            secret, from_env = expected
            assert got[A] == KeyInForce(A, secret, None if from_env else stored)

    asyncio.run(scenario())


def test_an_empty_env_key_is_no_key(db_url: str) -> None:
    households(db_url)

    async def scenario() -> None:
        async with connections_on(db_url) as connections:
            assert dict(await reader(connections, {A: "", B: ENV}).in_force()) == {B: KeyInForce(B, ENV, None)}

    asyncio.run(scenario())


def test_a_changed_env_key_is_ignored_while_the_row_exists_and_used_once_it_is_removed(db_url: str) -> None:
    first, _, alana = households(db_url)

    async def scenario() -> None:
        async with connections_on(db_url) as connections:
            stored = await add(connections, first, A, ROW, alana)
            keys = reader(connections, {A: "sk-env-changed-3333"})
            assert (await keys.in_force())[A].secret == ROW
            assert await connections.remove(stored, first, None)
            after = (await keys.in_force())[A]
            assert (after.secret, after.connection_id) == ("sk-env-changed-3333", None)

    asyncio.run(scenario())


def test_only_the_named_kinds_the_first_household_and_its_household_held_rows_are_read(db_url: str) -> None:
    first, second, alana = households(db_url)
    with psycopg.connect(db_url) as conn:
        kim = admin.add_person(conn, second, "Kim")

    async def scenario() -> None:
        async with connections_on(db_url) as connections:
            await add(connections, first, C, "sk-unlisted-kind", alana)
            await add(connections, second, A, "sk-other-household", kim)
            got = await reader(connections, {}, (A, B)).in_force()
            assert dict(got) == {}, "a row of a kind not asked for, or of another household, is not the first's key"

    asyncio.run(scenario())


def test_a_persons_own_row_of_the_kind_is_not_the_deployments_key(db_url: str) -> None:
    first, _, alana = households(db_url)
    kinds = services.get(ConnectionKinds).all()
    services.register(ConnectionKinds, ConnectionKinds(tuple(
        deployment_kind(k.name, holders=frozenset({"household", "person"})) if k.name == A else k for k in kinds)))

    async def scenario() -> None:
        async with connections_on(db_url) as connections:
            await add(connections, first, A, "sk-personal", alana, "person")
            got = await reader(connections, {A: ENV}).in_force()
            assert got[A] == KeyInForce(A, ENV, None)

    asyncio.run(scenario())


def test_without_the_sealing_key_the_envs_non_empty_keys_serve_and_nothing_raises() -> None:
    async def scenario() -> None:
        assert not NullConnections().can_open()
        got = await reader(NullConnections(), {A: ENV, B: ""}).in_force()
        assert dict(got) == {A: KeyInForce(A, ENV, None)}
        assert dict(await reader(NullConnections(), {}).in_force()) == {}

    asyncio.run(scenario())


def test_an_unreachable_database_raises_keys_unavailable_even_when_the_env_has_a_key() -> None:
    async def scenario() -> None:
        with pytest.raises(KeysUnavailable):
            await reader(Unreachable(), {A: ENV}).in_force()

    asyncio.run(scenario())


def test_a_stored_key_that_does_not_open_raises_keys_unavailable_not_the_envs_key(db_url: str) -> None:
    first, _, alana = households(db_url)

    async def scenario() -> None:
        async with connections_on(db_url) as connections:
            await add(connections, first, A, ROW, alana)
        async with connections_on(db_url, os.urandom(32)) as other:
            with pytest.raises(KeysUnavailable):
                await reader(other, {A: ENV}).in_force()

    asyncio.run(scenario())


def test_the_connections_are_asked_for_on_each_read(db_url: str) -> None:
    first, _, alana = households(db_url)
    holder: list[Connections] = [NullConnections()]
    keys = ConnectionProviderKeys(lambda: holder[0], (A,), {A: ENV})

    async def scenario() -> None:
        assert (await keys.in_force())[A].secret == ENV
        async with connections_on(db_url, SEALING_KEY) as connections:
            await add(connections, first, A, ROW, alana)
            holder[0] = connections
            assert (await keys.in_force())[A].secret == ROW
            holder[0] = Unreachable()
            with pytest.raises(KeysUnavailable):
                await keys.in_force()

    asyncio.run(scenario())


