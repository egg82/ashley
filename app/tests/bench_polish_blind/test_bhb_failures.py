"""A running turn that fails or is dropped leaves the messages it was handed as work: the oldest after it gets work of
its own, claimable at once, and any pod's sweep answers every one of them once. `InFlight.drop_leaving` is that
hand-over, in the transaction that drops the turn."""

import asyncio
import pytest
from ashley import services
from ashley.channels.respond import RespondRefused, respond
from ashley.conversations.conversations import Conversations
from ashley.conversations.inflight import Claim, InFlight, Leaving
from ashley.conversations.model import NewTurn, Turn
from ashley.inference.inference import InferenceRefused
from ashley.inference.model import Message
from bhb_support import World, entries_text, pods, reply, switch_on
from contract.conversations_support import blocked_backend, run
from psycopg import AsyncConnection
from test_bhb_window import LOCK


async def a_turn_that_fails(world: World, *later: str) -> None:
    """Her turn on the bench takes `later` messages (from another pod) during its first round, and then the model
    refuses: the turn ends with no answer."""
    async def others() -> None:
        for text in later:
            await world.from_pod(2, world.bench_say(text))

    world.tools.during = others
    world.model.play(switch_on(), InferenceRefused("no"))
    with pytest.raises(RespondRefused):
        await respond(world.bench_say("start"))


def test_a_failed_turn_leaves_its_message_to_a_sweep_that_answers_it_once(world: World) -> None:
    async def go() -> None:
        async with pods(world):
            await a_turn_that_fails(world, "and dim it")
            assert world.hers() == []
            assert world.work() == 1, "the message the failed turn was handed has work of its own"
            world.model.play(reply("handled both"))
            assert await world.sweep(2) == 1
            assert world.hers() == ["handled both"]
            assert any(isinstance(e, Message) and "and dim it" in e.text for e in world.model.prompts[-1].messages)
            assert world.work() == 0
            assert await world.sweep(1) == 0
            assert world.hers() == ["handled both"]

    run(go())


def test_several_messages_of_a_failed_turn_get_one_reply_from_the_sweep(world: World) -> None:
    async def go() -> None:
        async with pods(world):
            await a_turn_that_fails(world, "second", "third", "fourth")
            assert world.work() == 1, "only the oldest gets work; the rest are after it"
            world.model.play(reply("one reply for all"), reply("unexpected second reply"))
            assert await world.sweep(2) == 1
            assert await world.sweep(2) == 0
            assert await world.sweep(1) == 0
            assert world.hers() == ["one reply for all"]
            assert world.model.steps == 3, "two steps for the failed turn, one for the sweep's answer"
            text = " ".join(entries_text(world.model.prompts[-1]))
            for later in ("second", "third", "fourth"):
                assert later in text
            assert world.work() == 0

    run(go())


def test_the_sweep_of_a_failed_turn_s_message_hands_it_a_message_that_came_after_the_failure(world: World) -> None:
    async def go() -> None:
        async with pods(world):
            await a_turn_that_fails(world, "second")
            world.model.play(reply("one reply"))
            await world.from_pod(2, world.bench_say("arrived after"))  # the left work is running: it is pending
            assert world.hers() == [] and world.model.steps == 2
            await world.sweep(2)
            assert world.hers() == ["one reply"]
            assert "arrived after" in " ".join(entries_text(world.model.prompts[-1]))

    run(go())


async def seeded(world: World, count: int) -> tuple[Claim, list[Turn], Leaving, list[Turn]]:
    """A thread's first person turn with work, `count` person turns after it, and the Leaving that hands them on."""

    conversations, inflight = services.get(Conversations), services.get(InFlight)
    conv = await conversations.for_thread(world.who.household_id, "bench:leaving", "brainstorm", (world.who.id,))
    first = await conversations.add_turn(conv.id, NewTurn("person", "first", world.who.id, "private"))
    claim = await inflight.begin(conv.id, first.id, "mine")
    after = [await conversations.add_turn(conv.id, NewTurn("person", f"later {i}", world.who.id, "private"))
             for i in range(count)]
    seen: list[Turn] = []

    def seed(turn: Turn) -> str:
        seen.append(turn)
        return f"seed-for-{turn.text}"

    return claim, after, Leaving(conv.id, first.id, seed), seen


def test_drop_leaving_gives_the_oldest_unanswered_message_work_claimable_at_once(world: World) -> None:
    async def go() -> None:
        async with pods(world):
            inflight = services.get(InFlight)
            claim, after, leaving, seen = await seeded(world, 3)
            assert await inflight.drop_leaving(claim, leaving) is True
            assert [t.id for t in seen] == [after[0].id]
            orphans = await inflight.orphaned(10)
            assert [(o.claim.said_id, o.checkpoint) for o in orphans] == [(after[0].id, "seed-for-later 0")]
            assert await inflight.working(leaving.conversation_id) == frozenset({after[0].id})
            assert await inflight.orphaned(10) == [], "claimed by the first caller, once"

    run(go())


def test_drop_leaving_with_nothing_after_it_leaves_no_work(world: World) -> None:
    async def go() -> None:
        async with pods(world):
            inflight = services.get(InFlight)
            claim, _, leaving, seen = await seeded(world, 0)
            assert await inflight.drop_leaving(claim, leaving) is True
            assert seen == [] and await inflight.orphaned(10) == []
            assert world.work() == 0

    run(go())


def test_drop_leaving_leaves_nothing_once_her_final_answer_to_the_turn_is_stored(world: World) -> None:
    async def go() -> None:
        async with pods(world):
            claim, after, leaving, seen = await seeded(world, 1)
            await services.get(Conversations).add_turn(
                leaving.conversation_id, NewTurn("ashley", "answered", None, "private", answers=leaving.after,
                                                 handed=(after[0].id,)))
            await services.get(InFlight).drop_leaving(claim, leaving)
            assert seen == [] and world.work() == 0

    run(go())


def test_a_second_drop_of_the_same_work_leaves_no_second_work(world: World) -> None:
    async def go() -> None:
        async with pods(world):
            inflight = services.get(InFlight)
            claim, _, leaving, seen = await seeded(world, 2)
            assert await inflight.drop_leaving(claim, leaving) is True
            await inflight.drop_leaving(claim, leaving)
            assert world.work() == 1 and len(seen) == 1

    run(go())


def test_drop_leaving_by_a_runner_that_lost_the_work_drops_nothing_and_leaves_nothing(world: World) -> None:
    async def go() -> None:
        async with pods(world):
            inflight = services.get(InFlight)
            claim, _, leaving, seen = await seeded(world, 2)
            world.expire_claims()
            taken = await inflight.orphaned(5)
            assert [o.claim.said_id for o in taken] == [claim.said_id]
            assert await inflight.drop_leaving(claim, leaving) is False
            assert seen == [], "a runner that lost the turn leaves no work behind"
            assert world.work() == 1, "the new holder still has the work"

    run(go())


def test_a_message_being_stored_while_the_turn_is_dropped_is_left_to_the_new_work(world: World) -> None:
    """A message's store holds the conversation lock until it commits. The drop waits for it and then sees the
    message, so it is either left to the new work or stored after the drop, never lost between."""
    async def go() -> None:
        async with pods(world):
            inflight = services.get(InFlight)
            claim, _, leaving, seen = await seeded(world, 0)
            async with await AsyncConnection.connect(world.url) as storing:
                await storing.execute(LOCK.encode(), (leaving.conversation_id,))
                await storing.execute(
                    b"INSERT INTO turns (conversation_id, household_id, author, speaker_id, text, visibility, owner_id)"
                    b" SELECT conversation_id, household_id, 'person', speaker_id, 'in flight', visibility, owner_id"
                    b" FROM turns WHERE id = %s", (leaving.after,))
                dropping = asyncio.create_task(inflight.drop_leaving(claim, leaving))
                await blocked_backend(world.url)
                assert not dropping.done(), "the drop waits for the store that holds the lock"
            assert await asyncio.wait_for(dropping, 5) is True
            assert [t.text for t in seen] == ["in flight"], "the message stored under the lock is not lost"
            assert [o.checkpoint for o in await inflight.orphaned(5)] == ["seed-for-in flight"]

    run(go())
