"""Unavailability: an unreachable database, a read-only one, a connection lost mid-call and the unwired Null Object
all raise ConversationsUnavailable and write nothing. The composition root wires a real Conversations."""

import asyncio
from collections.abc import Generator

import psycopg
import pytest
from ashley import services
from ashley.conversations.conversations import Conversations, ConversationsUnavailable, NullConversations
from ashley.conversations.model import NewTurn
from ashley.db.database import Database
from ashley.settings import Settings
from ashley.wiring import wire
from contract_support import unreachable_conninfo
from conversations_support import blocked_backend, footprint, holding, household, person, run, service
from psycopg import sql


@pytest.fixture
def conversations_unwired() -> Generator[None]:
    services.unregister(Conversations)
    yield
    services.unregister(Conversations)


def test_every_call_raises_unavailable_when_the_database_is_unreachable() -> None:
    async def scenario() -> None:
        async with service(unreachable_conninfo(), connect_timeout_s=0.1) as conv:
            with pytest.raises(ConversationsUnavailable):
                await conv.start(1, "chat", [])
            with pytest.raises(ConversationsUnavailable):
                await conv.add_turn(1, NewTurn("person", "hello"))
            with pytest.raises(ConversationsUnavailable):
                await conv.get(1)

    run(scenario())


def test_the_null_object_raises_unavailable_on_every_call(conversations_unwired: None) -> None:
    null = services.get(Conversations)
    assert isinstance(null, NullConversations)
    assert isinstance(Conversations.null(), NullConversations)

    async def scenario() -> None:
        with pytest.raises(ConversationsUnavailable):
            await null.start(1, "chat", [])
        with pytest.raises(ConversationsUnavailable):
            await null.add_turn(1, NewTurn("person", "hello"))
        with pytest.raises(ConversationsUnavailable):
            await null.get(1)

    run(scenario())


def test_wiring_answers_a_real_conversations_over_the_wired_database(db_url: str, conversations_unwired: None) -> None:
    home = household(db_url)
    wire(Settings(database_url=db_url, build_version="test"))
    wired = services.get(Conversations)
    assert not isinstance(wired, NullConversations)

    async def scenario() -> None:
        db = services.get(Database)
        await db.open()
        try:
            started = await wired.start(home, "command", [])
            assert await wired.get(started.id) == started
        finally:
            await db.close()

    run(scenario())


def read_only(url: str) -> None:
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(sql.SQL("ALTER DATABASE {} SET default_transaction_read_only = on").format(
            sql.Identifier(str(conn.info.dbname))))


def test_writes_to_a_read_only_database_raise_unavailable_and_write_nothing(db_url: str) -> None:
    home = household(db_url)
    mine = person(db_url, home)

    async def make_one() -> int:
        async with service(db_url) as conv:
            return (await conv.start(home, "chat", [mine])).id

    cid = asyncio.run(make_one())
    read_only(db_url)
    before = footprint(db_url)

    async def scenario() -> None:
        async with service(db_url) as conv:
            with pytest.raises(ConversationsUnavailable):
                await conv.start(home, "chat", [mine])
            with pytest.raises(ConversationsUnavailable):
                await conv.add_turn(cid, NewTurn("person", "hello", mine))

    run(scenario())
    assert footprint(db_url) == before


def test_a_turn_whose_connection_dies_mid_call_raises_unavailable_and_writes_nothing(db_url: str) -> None:
    """A failover ends the session under a call; the turn is not stored and the caller is told to retry."""
    home = household(db_url)
    mine = person(db_url, home)

    async def scenario() -> None:
        async with service(db_url) as conv:
            cid = (await conv.start(home, "chat", [])).id
            before = footprint(db_url)
            async with holding(db_url, "SELECT 1 FROM conversations WHERE id = %s FOR UPDATE", (cid,)) as lock:
                call = asyncio.create_task(conv.add_turn(cid, NewTurn("person", "hello", mine)))
                await lock.execute("SELECT pg_terminate_backend(%s)", (await blocked_backend(db_url),))
                with pytest.raises(ConversationsUnavailable):
                    await call
            assert footprint(db_url) == before

    run(scenario())


def test_a_start_whose_connection_dies_mid_call_raises_unavailable_and_writes_nothing(db_url: str) -> None:
    home = household(db_url)
    mine = person(db_url, home)
    before = footprint(db_url)

    async def scenario() -> None:
        async with service(db_url) as conv:
            async with holding(db_url, "SELECT 1 FROM households WHERE id = %s FOR UPDATE", (home,)) as lock:
                call = asyncio.create_task(conv.start(home, "chat", [mine]))
                await lock.execute("SELECT pg_terminate_backend(%s)", (await blocked_backend(db_url),))
                with pytest.raises(ConversationsUnavailable):
                    await call

    run(scenario())
    assert footprint(db_url) == before
