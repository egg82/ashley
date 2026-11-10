"""The kinds are the application's to register, not the table's: the table accepts any kind, and the service refuses to
write one nothing registered, to read a row whose kind is gone, and sets a person on a row exactly for the personal
kinds."""

import asyncio

import psycopg
import pytest
from ashley import services
from ashley.connections.connections import ConnectionsUnavailable
from ashley.connections.kinds import ConnectionKinds
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import scalar
from test_connections_postgres import BASE, SECRET, connections_on, homes
from connection_legacy_support import put_of


pytestmark = pytest.mark.usefixtures("connection_kinds_wired")


def test_a_kind_nothing_registered_is_not_written(db_url: str) -> None:
    one, alana, _, _ = homes(db_url)

    async def scenario() -> None:
        async with connections_on(db_url) as connections:
            with pytest.raises(ValueError):
                await put_of(connections, one, "bitbucket", BASE, SECRET, alana)

    asyncio.run(scenario())
    assert scalar(db_url, "SELECT count(*) FROM connections") == 0


def test_a_stored_row_whose_kind_is_no_longer_registered_is_unavailable_not_a_wrong_answer(db_url: str) -> None:
    one, alana, _, _ = homes(db_url)

    async def scenario() -> None:
        async with connections_on(db_url) as connections:
            await put_of(connections, one, "sure", BASE, SECRET, alana)
            with psycopg.connect(db_url, autocommit=True) as conn:
                conn.execute("UPDATE connections SET kind = 'retired'")
            with pytest.raises(ConnectionsUnavailable):
                await connections.of_household(one)

    asyncio.run(scenario())


def test_the_table_takes_a_kind_the_adapters_add_later(db_url: str) -> None:
    one, _, _, _ = homes(db_url)
    with psycopg.connect(db_url, autocommit=True) as conn:
        conn.execute("INSERT INTO connections (household_id, kind, base_url, secret) VALUES (%s, 'music', %s, %s)",
                     (one, BASE, b"x"))
    assert scalar(db_url, "SELECT count(*) FROM connections WHERE kind = 'music'") == 1


def test_only_a_personal_kind_puts_a_person_on_the_row(db_url: str) -> None:
    one, alana, _, _ = homes(db_url)
    assert services.get(ConnectionKinds).is_personal("gitlab")

    async def scenario() -> None:
        async with connections_on(db_url) as connections:
            await put_of(connections, one, "sure", BASE, SECRET, alana)
            await put_of(connections, one, "gitlab", BASE, SECRET, alana)

    asyncio.run(scenario())
    with psycopg.connect(db_url) as conn:
        owners = dict(conn.execute("SELECT kind, person_id FROM connections").fetchall())
    assert owners == {"sure": None, "gitlab": alana}
