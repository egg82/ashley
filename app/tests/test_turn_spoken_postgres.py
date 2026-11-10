"""`turns.spoken` in Postgres: only her turn stores a voice and never a blank one (the service and the table both
refuse), it reads back on the turn, and `Conversations.spoken` returns it only to the household and thread that carries
the turn and only within the window by the database's clock."""

import asyncio
import time

import psycopg
import pytest
from ashley.conversations.conversations import ConversationError, Conversations, ConversationsUnavailable, RefusedTurn
from ashley.conversations.model import NewTurn
from contract.conversations_support import db_url as db_url, household, person, run, scalar, service, shift_back
from contract.conversations_support import migrated_template as migrated_template

VOICE = "It is noon."
THREAD = "person:1:web"


def turns(url: str) -> int:
    return int(scalar(url, "SELECT count(*) FROM turns"))


def started(url: str, home: int, thread: str = THREAD) -> int:
    async def scenario() -> int:
        async with service(url) as conversations:
            return (await conversations.for_thread(home, thread, "chat", [])).id

    return asyncio.run(scenario())


def test_her_turn_stores_its_voice_and_reads_it_back(db_url: str) -> None:
    home = household(db_url)
    alana = person(db_url, home)

    async def scenario() -> None:
        async with service(db_url) as conversations:
            made = await conversations.for_thread(home, THREAD, "chat", [alana])
            said = await conversations.add_turn(made.id, NewTurn("person", "time?", alana))
            hers = await conversations.add_turn(made.id, NewTurn("ashley", "12:00", answers=said.id, spoken=VOICE))
            plain = await conversations.add_turn(made.id, NewTurn("ashley", "ok"))
            assert (hers.spoken, plain.spoken, said.spoken) == (VOICE, None, None)
            got = await conversations.get(made.id)
            assert got is not None and [t.spoken for t in got.turns] == [None, VOICE, None]
            assert [t.text for t in got.turns] == ["time?", "12:00", "ok"]

    run(scenario())


@pytest.mark.parametrize("turn", [
    NewTurn("person", "hi", spoken=VOICE), NewTurn("household", "wake", spoken=VOICE),
    NewTurn("ashley", "hi", spoken=""), NewTurn("ashley", "hi", spoken="  \n")])
def test_a_voice_on_another_author_or_a_blank_one_is_refused_and_nothing_is_stored(db_url: str, turn: NewTurn) -> None:
    home = household(db_url)
    cid = started(db_url, home)

    async def scenario() -> None:
        async with service(db_url) as conversations:
            with pytest.raises(RefusedTurn):
                await conversations.add_turn(cid, turn)

    run(scenario())
    assert turns(db_url) == 0
    assert issubclass(RefusedTurn, ConversationError) and issubclass(RefusedTurn, ValueError)


@pytest.mark.parametrize("author, spoken", [("person", "x"), ("household", "x"), ("ashley", "")])
def test_the_table_refuses_what_the_service_refuses(db_url: str, author: str, spoken: str) -> None:
    home = household(db_url)
    cid = started(db_url, home)
    with psycopg.connect(db_url, autocommit=True) as conn, pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("INSERT INTO turns (conversation_id, household_id, author, text, spoken) "
                     "VALUES (%s, %s, %s, 'hi', %s)", (cid, home, author, spoken))
    assert turns(db_url) == 0


def test_spoken_reaches_only_the_household_and_thread_that_carries_the_turn(db_url: str) -> None:
    mine, theirs = household(db_url, "mine"), household(db_url, "theirs")

    async def scenario() -> None:
        async with service(db_url) as conversations:
            here = await conversations.for_thread(mine, THREAD, "chat", [])
            other = await conversations.for_thread(mine, "device:9", "chat", [])
            there = await conversations.for_thread(theirs, "person:2:web", "chat", [])
            voiced = await conversations.add_turn(here.id, NewTurn("ashley", "a", spoken=VOICE))
            mute = await conversations.add_turn(here.id, NewTurn("ashley", "b"))
            said = await conversations.add_turn(here.id, NewTurn("person", "c"))
            elsewhere = await conversations.add_turn(other.id, NewTurn("ashley", "d", spoken="device voice"))
            foreign = await conversations.add_turn(there.id, NewTurn("ashley", "e", spoken="their voice"))
            ask = conversations.spoken
            assert await ask(mine, THREAD, voiced.id, 120) == VOICE, "control: the owner hears it"
            assert await ask(mine, "device:9", elsewhere.id, 120) == "device voice"
            assert await ask(mine, "device:9", voiced.id, 120) is None, "another thread of the household"
            assert await ask(mine, THREAD, elsewhere.id, 120) is None
            assert await ask(theirs, THREAD, voiced.id, 120) is None, "another household, this thread"
            assert await ask(mine, "person:2:web", foreign.id, 120) is None
            assert await ask(theirs, "person:2:web", foreign.id, 120) == "their voice"
            assert await ask(mine, THREAD, mute.id, 120) is None and await ask(mine, THREAD, said.id, 120) is None
            assert await ask(mine, THREAD, voiced.id + 10_000, 120) is None

    run(scenario())


def test_a_voice_is_fetchable_only_within_the_window_by_the_databases_clock(db_url: str) -> None:
    home = household(db_url)
    cid = started(db_url, home)

    async def add() -> int:
        async with service(db_url) as conversations:
            return (await conversations.add_turn(cid, NewTurn("ashley", "a", spoken=VOICE))).id

    turn = asyncio.run(add())

    async def ask(within_s: int) -> str | None:
        async with service(db_url) as conversations:
            return await conversations.spoken(home, THREAD, turn, within_s)

    assert asyncio.run(ask(120)) == VOICE, "control: fresh"
    shift_back(db_url, cid, 100)
    assert asyncio.run(ask(120)) == VOICE
    assert asyncio.run(ask(60)) is None
    shift_back(db_url, cid, 100)
    assert asyncio.run(ask(120)) is None
    assert asyncio.run(ask(300)) == VOICE
    assert scalar(db_url, "SELECT spoken FROM turns WHERE id = %s", (turn,)) == VOICE, "expiry keeps the row"


def test_the_window_does_not_follow_this_processes_clock(db_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    home = household(db_url)
    cid = started(db_url, home)

    async def scenario() -> str | None:
        async with service(db_url) as conversations:
            turn = await conversations.add_turn(cid, NewTurn("ashley", "a", spoken=VOICE))
            return await conversations.spoken(home, THREAD, turn.id, 120)

    real = time.time
    monkeypatch.setattr(time, "time", lambda: real() + 86_400)
    assert asyncio.run(scenario()) == VOICE


def test_an_unwired_service_is_unavailable() -> None:
    with pytest.raises(ConversationsUnavailable):
        asyncio.run(Conversations.null().spoken(1, THREAD, 1, 120))
