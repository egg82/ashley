"""A WebSocket command Home Assistant answers successfully through a stored connection moves its `checked_at`, once per
command; a command it rejects or a token it refuses leaves it."""

import asyncio
import os
from collections.abc import AsyncGenerator, Coroutine, Generator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, TypeVar

import psycopg
import pytest
from ashley import services
from ashley.connections.connections import Connections
from ashley.connections.kinds import ConnectionKinds
from ashley.connections.postgres import PostgresConnections
from ashley.connections.sealing import VERSION, Sealer
from ashley.db.pool import PoolDatabase
from ashley.home_assistant.connected_homes import ConnectedHomes
from ashley.home_assistant.ha_socket import Commands
from ashley.home_assistant.homes import Homes
from ashley.home_assistant.house import HouseRejected, HouseUnavailable
from ashley.home_assistant.house_settings import load as load_house_settings
from ashley.people import admin
from ashley.wiring import CONNECTION_KINDS
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import scalar

from house_stand_support import TOKEN, Stand, serving
from connection_legacy_support import put_of

T = TypeVar("T")

LIST = {"type": "config/area_registry/list"}
KEY = os.urandom(32)


@pytest.fixture(autouse=True)
def services_unwired() -> Generator[None]:
    """The services this file registers start and end each test as their Null Objects."""
    for interface in (Connections, ConnectionKinds, Homes):
        services.unregister(interface)
    yield
    for interface in (Connections, ConnectionKinds, Homes):
        services.unregister(interface)


def go(scenario: Coroutine[Any, Any, T]) -> T:
    async def bounded() -> T:
        return await asyncio.wait_for(scenario, 25.0)

    return asyncio.run(bounded())


@asynccontextmanager
async def connections(url: str) -> AsyncGenerator[Connections]:
    database = PoolDatabase(url)
    await database.open()
    service = PostgresConnections(database, Sealer({VERSION: KEY}))
    services.register(ConnectionKinds, ConnectionKinds(CONNECTION_KINDS))
    services.register(Connections, service)
    try:
        yield service
    finally:
        await database.close()


def stored_at(url: str, household: int) -> datetime:
    return scalar(url, "SELECT checked_at FROM connections WHERE household_id = %s AND kind = 'home_assistant'",
                  (household,))


def age(url: str, household: int) -> datetime:
    """Move the stored connection's `checked_at` an hour into the past and return it, so a later move is unmistakable."""
    return scalar(url, "UPDATE connections SET checked_at = checked_at - interval '1 hour' WHERE household_id = %s "
                       "AND kind = 'home_assistant' RETURNING checked_at", (household,))


async def commands_over(c: Connections, db_url: str, base_url: str, token: str) -> tuple[Commands, int]:
    """Commands over the household's stored connection to `base_url`."""
    with psycopg.connect(db_url) as conn:
        home = admin.add_household(conn, "home", "America/Denver")
        alana = admin.add_person(conn, home, "Alana")
    await put_of(c, home, "home_assistant", base_url, token, alana)
    services.register(Homes, ConnectedHomes(c))
    house = await services.get(Homes).of(home)
    assert house is not None
    return Commands(house.home_assistant, load_house_settings()), home


def test_a_successful_command_moves_checked_at_once_per_command(db_url: str) -> None:
    async def scenario() -> None:
        with serving(Stand()) as url:
            async with connections(db_url) as c:
                commands, home = await commands_over(c, db_url, url, TOKEN)
                was = age(db_url, home)
                await commands.run(LIST)
                first = stored_at(db_url, home)
                assert first > was
                await commands.run(LIST)
                assert stored_at(db_url, home) > first

    go(scenario())


def test_a_command_home_assistant_rejects_leaves_checked_at(db_url: str) -> None:
    async def scenario() -> None:
        stand = Stand(reject="no such thing")
        with serving(stand) as url:
            async with connections(db_url) as c:
                commands, home = await commands_over(c, db_url, url, TOKEN)
                was = age(db_url, home)
                with pytest.raises(HouseRejected):
                    await commands.run({"type": "input_boolean/delete", "input_boolean_id": "x"})
                assert stored_at(db_url, home) == was

    go(scenario())


def test_a_refused_token_leaves_checked_at(db_url: str) -> None:
    async def scenario() -> None:
        with serving(Stand()) as url:
            async with connections(db_url) as c:
                commands, home = await commands_over(c, db_url, url, "wrong-token")
                was = age(db_url, home)
                with pytest.raises(HouseUnavailable):
                    await commands.run(LIST)
                assert stored_at(db_url, home) == was

    go(scenario())
