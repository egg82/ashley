"""`InFlight.working`: the person turns of a conversation still owed an answer that have a work row. Postgres is real."""

import asyncio

from ashley import services
from ashley.conversations.conversations import Conversations
from ashley.conversations.inflight import InFlight
from ashley.conversations.model import NewTurn
from contract.conversations_support import run
from contract.test_inflight_resume import CLAIM_S, World
from ipb_support import rig


def test_the_null_inflight_has_nothing_working() -> None:
    got = run_working(InFlight.null(), 1)
    assert got == frozenset() and isinstance(got, frozenset)


def run_working(inflight: InFlight, conversation_id: int) -> frozenset[int]:
    out: list[frozenset[int]] = []

    async def go() -> None:
        out.append(await inflight.working(conversation_id))

    run(go())
    return out[0]


def test_a_turn_with_a_work_row_is_working_and_a_turn_without_is_not(world: World) -> None:
    async def go() -> None:
        async with rig(world) as r:
            claim, conv = await r.began()
            plain = await services.get(Conversations).add_turn(conv, NewTurn("person", "no work", world.who.id))
            working = await services.get(InFlight).working(conv)
            assert working == frozenset({claim.said_id}) and plain.id not in working

    run(go())


def test_a_conversation_nothing_was_said_in_has_none_working(world: World) -> None:
    async def go() -> None:
        async with rig(world):
            assert await services.get(InFlight).working(987654) == frozenset()

    run(go())


def test_work_in_another_conversation_is_not_this_ones(world: World) -> None:
    async def go() -> None:
        async with rig(world) as r:
            one, conv_one = await r.began("a")
            two, conv_two = await r.began("b")
            inflight = services.get(InFlight)
            assert await inflight.working(conv_one) == frozenset({one.said_id})
            assert await inflight.working(conv_two) == frozenset({two.said_id})

    run(go())


def test_two_turns_of_one_conversation_with_work_are_both_working(world: World) -> None:
    async def go() -> None:
        async with rig(world) as r:
            first, conv = await r.began("a")
            second_turn = await services.get(Conversations).add_turn(conv, NewTurn("person", "b", world.who.id))
            second = await services.get(InFlight).begin(conv, second_turn.id, "cp2")
            assert await services.get(InFlight).working(conv) == frozenset({first.said_id, second.said_id})

    run(go())


def test_her_stored_answer_ends_it_for_that_turn_only(world: World) -> None:
    async def go() -> None:
        async with rig(world) as r:
            first, conv = await r.began("a")
            second_turn = await services.get(Conversations).add_turn(conv, NewTurn("person", "b", world.who.id))
            second = await services.get(InFlight).begin(conv, second_turn.id, "cp2")
            await r.outbox.answer(first, NewTurn("ashley", "A.", answers=first.said_id), [])
            assert await services.get(InFlight).working(conv) == frozenset({second.said_id})

    run(go())


def test_a_turn_that_failed_is_no_longer_working(world: World) -> None:
    async def go() -> None:
        async with rig(world) as r:
            claim, conv = await r.began()
            assert await services.get(InFlight).drop(claim)
            assert await services.get(InFlight).working(conv) == frozenset()

    run(go())


def test_work_whose_claim_ran_out_is_working_until_resumed_and_ended(world: World) -> None:
    async def go() -> None:
        async with rig(world) as r:
            claim, conv = await r.began()
            await asyncio.sleep(CLAIM_S * 1.5)
            assert await services.get(InFlight).working(conv) == frozenset({claim.said_id})
            (orphan,) = await services.get(InFlight).orphaned(10)
            await r.outbox.answer(orphan.claim, NewTurn("ashley", "Done.", answers=orphan.claim.said_id), [])
            assert await services.get(InFlight).working(conv) == frozenset()

    run(go())


def test_a_held_line_does_not_end_it(world: World) -> None:
    async def go() -> None:
        async with rig(world) as r:
            claim, conv = await r.began()
            await services.get(Conversations).add_turn(
                conv, NewTurn("ashley", "Let me check.", follows=True, answers=claim.said_id))
            assert await services.get(InFlight).working(conv) == frozenset({claim.said_id})

    run(go())


def test_work_kept_only_for_a_memory_act_after_her_answer_is_not_working(world: World) -> None:
    async def go() -> None:
        async with rig(world) as r:
            claim, conv = await r.began()
            await r.outbox.answer(claim, NewTurn("ashley", "Done.", answers=claim.said_id), [], lambda stored: "act")
            assert await services.get(InFlight).working(conv) == frozenset()

    run(go())
