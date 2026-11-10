"""PostgresConversations.for_thread against a real database: continue, start, another household's thread, races."""

from typing import Any

import pytest
from ashley import logs
from ashley.conversations.conversations import UnknownHousehold, UnknownPerson
from ashley.conversations.model import Conversation, NewTurn
from contract.conversations_support import (db_url as db_url, events, gather_settled, household,
                                            migrated_template as migrated_template, person, place_before_now, run,
                                            scalar, service)


def test_a_new_thread_starts_one_and_the_next_call_continues_it(db_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    home = household(db_url)
    me = person(db_url, home)
    logs.setup()

    async def scenario() -> None:
        async with service(db_url) as conv:
            first = await conv.for_thread(home, "device:1", "chat", [me, me])
            await conv.add_turn(first.id, NewTurn("person", "hello", me))
            again = await conv.for_thread(home, "device:1", "command", [])
            assert first.turns == () and first.participants == {me} and first.kind == "chat"
            assert again.id == first.id and len(again.turns) == 1 and again.kind == "chat"

    run(scenario())
    out = capsys.readouterr().out
    assert [e["outcome"] for e in events(out, "conversation.thread")] == ["started", "continued"]
    assert len(events(out, "conversation.started")) == 1


def test_a_closed_conversation_is_replaced_and_the_thread_points_at_the_new_one(db_url: str) -> None:
    home = household(db_url)

    async def scenario() -> None:
        async with service(db_url) as conv:
            old = await conv.for_thread(home, "t", "command", [])
            place_before_now(db_url, old.id, 101)
            new = await conv.for_thread(home, "t", "command", [])
            assert new.id != old.id and new.state == "open"
            assert (await conv.for_thread(home, "t", "command", [])).id == new.id

    run(scenario())


def test_an_idle_conversation_is_continued(db_url: str) -> None:
    home = household(db_url)

    async def scenario() -> None:
        async with service(db_url) as conv:
            old = await conv.for_thread(home, "t", "command", [])
            place_before_now(db_url, old.id, 50)
            again = await conv.for_thread(home, "t", "command", [])
            assert again.id == old.id and again.state == "idle"

    run(scenario())


def test_another_households_conversation_counts_as_none(db_url: str) -> None:
    home, away = household(db_url), household(db_url)

    async def scenario() -> None:
        async with service(db_url) as conv:
            theirs = await conv.for_thread(away, "t", "chat", [])
            mine = await conv.for_thread(home, "t", "chat", [])
            assert mine.id != theirs.id and mine.household_id == home

    run(scenario())
    assert scalar(db_url, "SELECT household_id FROM conversation_threads WHERE thread = 't'") == home


@pytest.mark.parametrize("seed", ["fresh", "closed"])
def test_racing_calls_on_one_thread_agree(db_url: str, seed: str) -> None:
    home = household(db_url)

    async def scenario() -> None:
        async with service(db_url) as conv, service(db_url) as other_site:
            if seed == "closed":
                old = await conv.for_thread(home, "t", "command", [])
                place_before_now(db_url, old.id, 101)
            got = await gather_settled(*((conv if i % 2 else other_site).for_thread(home, "t", "command", [])
                                         for i in range(12)))
            assert all(isinstance(c, Conversation) for c in got), got
            assert len({c.id for c in got if isinstance(c, Conversation)}) == 1

    run(scenario())
    started = 2 if seed == "closed" else 1
    assert scalar(db_url, "SELECT count(*) FROM conversations") == started


def test_errors_write_nothing(db_url: str) -> None:
    home = household(db_url)
    stranger = person(db_url, household(db_url))
    outside: Any = "nope"  # Any: a kind outside Kind is the case under test

    async def scenario() -> None:
        async with service(db_url) as conv:
            for thread in ("", "  "):
                with pytest.raises(ValueError):
                    await conv.for_thread(home, thread, "chat", [])
            with pytest.raises(ValueError):
                await conv.for_thread(home, "t", outside, [])
            with pytest.raises(UnknownPerson):
                await conv.for_thread(home, "t", "chat", [stranger])
            with pytest.raises(UnknownHousehold):
                await conv.for_thread(home + 1000, "t", "chat", [])

    run(scenario())
    assert scalar(db_url, "SELECT count(*) FROM conversations") == 0
    assert scalar(db_url, "SELECT count(*) FROM conversation_threads") == 0


def test_on_thread_reads_what_the_thread_last_carried_and_starts_nothing(db_url: str) -> None:
    home, other = household(db_url), household(db_url)
    me = person(db_url, home)

    async def scenario() -> None:
        async with service(db_url) as conv:
            assert await conv.on_thread(home, "person:1:web") is None
            made = await conv.for_thread(home, "person:1:web", "chat", [me])
            await conv.add_turn(made.id, NewTurn("person", "hello", me))
            await conv.add_turn(made.id, NewTurn("ashley", "hi"))
            got = await conv.on_thread(home, "person:1:web")
            assert got is not None and got.id == made.id and got.state == "open"
            assert [(t.author, t.text) for t in got.turns] == [("person", "hello"), ("ashley", "hi")]
            assert await conv.on_thread(other, "person:1:web") is None
            place_before_now(db_url, made.id, 10_001)
            closed = await conv.on_thread(home, "person:1:web")
            assert closed is not None and closed.id == made.id and closed.state == "closed"

    run(scenario())
    assert scalar(db_url, "SELECT count(*) FROM conversations WHERE household_id = %s", (home,)) == 1
