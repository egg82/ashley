"""`Outbox.answer` and `InFlight.finish(after=)` against Postgres: her answer stored and queued in one transaction or
neither, and the work kept, still claimed, when something is left to do after her turn."""

import asyncio

import pytest
from ashley import services
from ashley.channels.model import Outbound
from ashley.channels.outbox import Pushed
from ashley.conversations.conversations import Conversations
from ashley.conversations.inflight import Claim, ClaimLost, InFlight
from ashley.conversations.model import NewTurn, Turn
from contract.conversations_support import run
from contract.test_inflight_resume import CLAIM_S, World
from irb_support import stack


async def began(world: World) -> tuple[Claim, Pushed, int]:
    conversations = services.get(Conversations)
    started = await conversations.start(world.who.household_id, "chat", [world.who.id])
    said = await conversations.add_turn(started.id, NewTurn("person", "hi", world.who.id, "private", world.who.id))
    claim = await services.get(InFlight).begin(started.id, said.id, "first")
    return claim, Pushed(world.who.household_id, "discord:5", Outbound(started.id, "text", "Done.")), said.id


def test_an_answer_is_queued_and_stored_together_and_ends_the_work(world: World) -> None:
    async def go() -> None:
        async with stack(world) as s:
            claim, pushed, said = await began(world)
            stored = await s.outbox.answer(claim, NewTurn("ashley", "Done.", answers=said), [pushed])
            assert (stored.author, stored.text) == ("ashley", "Done.")
            (queued,) = await s.outbox.take("")
            assert (queued.thread, queued.household_id, queued.outbound.body) == ("discord:5", pushed.household_id,
                                                                                  "Done.")
            await asyncio.sleep(CLAIM_S * 1.5)
            assert await services.get(InFlight).orphaned(10) == []

    run(go())
    assert world.hers() == ["Done."]


def test_an_answer_the_conversation_refuses_is_not_queued(world: World) -> None:
    async def go() -> None:
        async with stack(world) as s:
            claim, pushed, said = await began(world)
            with pytest.raises(ValueError):
                await s.outbox.answer(claim, NewTurn("ashley", "  ", answers=said), [pushed])
            assert await s.outbox.take("") == []
            await asyncio.sleep(CLAIM_S * 1.5)
            assert len(await services.get(InFlight).orphaned(10)) == 1, "the work is kept"

    run(go())
    assert world.hers() == []


def test_a_failure_after_her_turn_was_stored_undoes_the_queueing_and_the_turn(world: World) -> None:
    def broken(stored: Turn) -> str:
        raise RuntimeError("cannot build the checkpoint")

    async def go() -> None:
        async with stack(world) as s:
            claim, pushed, said = await began(world)
            with pytest.raises(RuntimeError):
                await s.outbox.answer(claim, NewTurn("ashley", "Done.", answers=said), [pushed], broken)
            assert await s.outbox.take("") == []

    run(go())
    assert world.hers() == []


def test_an_answer_with_something_left_to_do_keeps_the_work_with_the_checkpoint_it_names(world: World) -> None:
    seen: list[Turn] = []

    def left(stored: Turn) -> str:
        seen.append(stored)
        return f"act-after-{stored.id}"

    async def go() -> None:
        async with stack(world) as s:
            claim, pushed, said = await began(world)
            stored = await s.outbox.answer(claim, NewTurn("ashley", "Done.", answers=said), [pushed], left)
            assert seen == [stored] and stored.author == "ashley"
            assert len(await s.outbox.take("")) == 1
            assert await services.get(InFlight).orphaned(10) == [], "still the first runner's"
            await services.get(InFlight).renew(claim)
            await asyncio.sleep(CLAIM_S * 1.5)
            (orphan,) = await services.get(InFlight).orphaned(10)
            assert orphan.checkpoint == f"act-after-{stored.id}" and orphan.claim.said_id == said
            with pytest.raises(ClaimLost):
                await services.get(InFlight).save(claim, "late")

    run(go())
    assert world.hers() == ["Done."]


def test_finish_with_something_left_does_not_let_the_turn_be_answered_again(world: World) -> None:
    async def go() -> None:
        async with stack(world):
            claim, _, said = await began(world)
            inflight = services.get(InFlight)
            await inflight.finish(claim, NewTurn("ashley", "Done.", answers=said), lambda t: "left")
            with pytest.raises(ValueError):
                await inflight.begin(claim.conversation_id, said, "again")

    run(go())


def test_begin_refuses_a_turn_whose_answer_is_stored(world: World) -> None:
    async def go() -> None:
        async with stack(world):
            conversations = services.get(Conversations)
            started = await conversations.start(world.who.household_id, "chat", [world.who.id])
            said = await conversations.add_turn(started.id, NewTurn("person", "hi", world.who.id, "private",
                                                                    world.who.id))
            await conversations.add_turn(started.id, NewTurn("ashley", "Hello.", answers=said.id))
            with pytest.raises(ValueError):
                await services.get(InFlight).begin(started.id, said.id, "late")
            await asyncio.sleep(CLAIM_S * 1.5)
            assert await services.get(InFlight).orphaned(10) == []

    run(go())


def test_begin_still_takes_a_turn_that_only_has_a_held_line(world: World) -> None:
    async def go() -> None:
        async with stack(world):
            conversations = services.get(Conversations)
            started = await conversations.start(world.who.household_id, "chat", [world.who.id])
            said = await conversations.add_turn(started.id, NewTurn("person", "hi", world.who.id, "private",
                                                                    world.who.id))
            await conversations.add_turn(started.id, NewTurn("ashley", "Let me check.", follows=True,
                                                             answers=said.id))
            claim = await services.get(InFlight).begin(started.id, said.id, "held")
            assert claim.said_id == said.id

    run(go())


def test_a_runner_that_lost_the_work_cannot_finish_it_leaving_something_to_do(world: World) -> None:
    async def go() -> None:
        async with stack(world) as s:
            claim, pushed, said = await began(world)
            await asyncio.sleep(CLAIM_S * 1.5)
            (taken,) = await services.get(InFlight).orphaned(10)
            assert taken.claim.holder != claim.holder
            turn = NewTurn("ashley", "Done.", answers=said)
            with pytest.raises(ClaimLost):
                await services.get(InFlight).finish(claim, turn, lambda t: "left")
            with pytest.raises(ClaimLost):
                await s.outbox.answer(claim, turn, [pushed], lambda t: "left")
            assert await s.outbox.take("") == []
            assert (await services.get(InFlight).renew(taken.claim)) is None

    run(go())
    assert world.hers() == []
