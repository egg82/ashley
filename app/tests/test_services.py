"""The locator: a registered provider answers, an unregistered interface gets its Null Object, and a wrong
registration is refused."""

import asyncio
from contextlib import AbstractAsyncContextManager
from typing import Any

import pytest
from ashley import services
from ashley.db.database import Database, DatabaseUnavailable, NullDatabase, Probe
from psycopg import AsyncConnection


class FakeDatabase(Database):
    async def open(self) -> None:
        pass

    async def close(self) -> None:
        pass

    async def probe(self) -> Probe:
        return Probe(reachable=True, writable=True)

    def connection(self) -> AbstractAsyncContextManager[AsyncConnection[tuple[Any, ...]]]:
        raise DatabaseUnavailable("a fake has no connections")


class NotAService:
    pass


def test_an_unregistered_interface_answers_its_null_object() -> None:
    assert isinstance(services.get(Database), NullDatabase)


def test_the_null_database_reaches_nothing() -> None:
    assert asyncio.run(services.get(Database).probe()) == Probe(reachable=False, writable=False)


def test_a_registered_provider_answers_and_unregistering_restores_the_null() -> None:
    fake = FakeDatabase()
    services.register(Database, fake)
    assert services.get(Database) is fake
    assert asyncio.run(services.get(Database).probe()).reachable
    services.unregister(Database)
    assert isinstance(services.get(Database), NullDatabase)


def test_a_provider_of_another_type_is_refused() -> None:
    wrong: Any = NotAService()
    with pytest.raises(TypeError):
        services.register(Database, wrong)
    assert isinstance(services.get(Database), NullDatabase)
