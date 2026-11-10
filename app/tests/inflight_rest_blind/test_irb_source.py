"""A person turn's source (`discord:<message id>`) is stored once per household; her turns carry none."""

import asyncio

import pytest
from ashley import services
from ashley.conversations.conversations import Conversations
from ashley.conversations.model import NewTurn
from contract.conversations_support import household, person, run, scalar
from contract.test_inflight_resume import World
from irb_support import stack

ONCE = "discord:9001"


def said(who: int, text: str = "hi", source: str | None = ONCE) -> NewTurn:
    return NewTurn("person", text, who, "private", who, source=source)


def turns(url: str) -> int:
    return int(scalar(url, "SELECT count(*) FROM turns"))


def test_a_source_is_stored_once_in_a_household_whichever_conversation_it_is_handed_to(world: World) -> None:
    async def go() -> None:
        async with stack(world):
            conversations = services.get(Conversations)
            a = await conversations.start(world.who.household_id, "chat", [world.who.id])
            b = await conversations.start(world.who.household_id, "chat", [world.who.id])
            first = await conversations.add_turn(a.id, said(world.who.id))
            again = await conversations.add_turn(a.id, said(world.who.id, "other words"))
            elsewhere = await conversations.add_turn(b.id, said(world.who.id))
            assert again.id == first.id and elsewhere.id == first.id
            assert (again.text, elsewhere.text) == ("hi", "hi")

    run(go())
    assert turns(world.url) == 1


def test_a_source_in_another_household_is_its_own_turn(world: World) -> None:
    other = household(world.url, "other")
    stranger = person(world.url, other, "Sam")

    async def go() -> None:
        async with stack(world):
            conversations = services.get(Conversations)
            mine = await conversations.start(world.who.household_id, "chat", [world.who.id])
            theirs = await conversations.start(other, "chat", [stranger])
            one = await conversations.add_turn(mine.id, said(world.who.id))
            two = await conversations.add_turn(theirs.id, said(stranger))
            assert one.id != two.id
            assert (await conversations.add_turn(theirs.id, said(stranger))).id == two.id

    run(go())
    assert turns(world.url) == 2


def test_turns_without_a_source_and_with_different_sources_are_all_stored(world: World) -> None:
    async def go() -> None:
        async with stack(world):
            conversations = services.get(Conversations)
            c = await conversations.start(world.who.household_id, "chat", [world.who.id])
            for source in (None, None, "discord:1", "discord:2"):
                await conversations.add_turn(c.id, said(world.who.id, source=source))

    run(go())
    assert turns(world.url) == 4


def test_her_turn_with_a_source_is_refused_and_stores_nothing(world: World) -> None:
    async def go() -> None:
        async with stack(world):
            conversations = services.get(Conversations)
            c = await conversations.start(world.who.household_id, "chat", [world.who.id])
            with pytest.raises(ValueError):
                await conversations.add_turn(c.id, NewTurn("ashley", "hello", source=ONCE))

    run(go())
    assert turns(world.url) == 0


def test_a_source_already_stored_is_returned_even_when_her_answer_to_it_is_stored(world: World) -> None:
    async def go() -> None:
        async with stack(world):
            conversations = services.get(Conversations)
            c = await conversations.start(world.who.household_id, "chat", [world.who.id])
            first = await conversations.add_turn(c.id, said(world.who.id))
            await conversations.add_turn(c.id, NewTurn("ashley", "Hello.", answers=first.id))
            assert (await conversations.add_turn(c.id, said(world.who.id))).id == first.id

    run(go())
    assert turns(world.url) == 2


def test_a_source_handed_in_by_many_racing_pods_is_one_turn_whichever_conversation_each_names(world: World) -> None:
    async def go() -> None:
        async with stack(world):
            conversations = services.get(Conversations)
            threads = [await conversations.start(world.who.household_id, "chat", [world.who.id]) for _ in range(8)]
            got = await asyncio.gather(*(conversations.add_turn(c.id, said(world.who.id)) for c in threads))
            assert len({t.id for t in got}) == 1

    run(go())
    assert turns(world.url) == 1
