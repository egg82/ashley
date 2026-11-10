"""InFlight.finish and drop, blind: her turn and the end of the work are one transaction, held only by the claim."""

import asyncio

import pytest
from ashley.conversations.conversations import ConversationClosed
from ashley.conversations.inflight import ClaimLost
from ashley.conversations.model import NewTurn
from contract.conversations_support import place_before_now, run
from ifb_support import rig


def test_finish_stores_her_turn_and_removes_the_work(db_url: str) -> None:
    async def go() -> None:
        async with rig(db_url) as r:
            claim = await r.begin()
            turn = await r.inflight.finish(claim, NewTurn("ashley", "Done."))
            assert (turn.author, turn.text) == ("ashley", "Done.")
            conv = await r.conversations.get(claim.conversation_id)
            assert conv is not None
            assert [(t.author, t.text) for t in conv.turns] == [("person", "hello"), ("ashley", "Done.")]
            assert conv.turns[-1].id == turn.id
            assert await r.rows() == 0
            await r.expire_all()
            assert await r.inflight.orphaned(10) == []

    run(go())


def test_a_second_finish_is_claim_lost_and_stores_nothing_more(db_url: str) -> None:
    async def go() -> None:
        async with rig(db_url) as r:
            claim = await r.begin()
            await r.inflight.finish(claim, NewTurn("ashley", "one"))
            with pytest.raises(ClaimLost):
                await r.inflight.finish(claim, NewTurn("ashley", "two"))
            assert await r.hers() == ["one"]

    run(go())


def test_finish_after_drop_is_claim_lost(db_url: str) -> None:
    async def go() -> None:
        async with rig(db_url) as r:
            claim = await r.begin()
            await r.inflight.drop(claim)
            with pytest.raises(ClaimLost):
                await r.inflight.finish(claim, NewTurn("ashley", "late"))
            assert await r.hers() == []

    run(go())


def test_two_finishes_at_once_store_one_turn(db_url: str) -> None:
    async def go() -> None:
        async with rig(db_url) as r:
            claim = await r.begin()
            out = await asyncio.gather(*(r.inflight.finish(claim, NewTurn("ashley", f"r{i}")) for i in range(4)),
                                       return_exceptions=True)
            assert sum(isinstance(o, ClaimLost) for o in out) == 3
            assert len(await r.hers()) == 1

    run(go())


def test_the_old_and_the_new_runner_finishing_at_once_store_one_turn(db_url: str) -> None:
    async def go() -> None:
        async with rig(db_url) as r:
            old = await r.begin()
            await r.expire(old)
            [taken] = await r.inflight.orphaned(10)
            out = await asyncio.gather(r.inflight.finish(old, NewTurn("ashley", "old")),
                                       r.inflight.finish(taken.claim, NewTurn("ashley", "new")),
                                       return_exceptions=True)
            assert isinstance(out[0], ClaimLost)
            assert await r.hers() == ["new"]

    run(go())


def test_finish_after_the_claim_lapsed_but_was_not_taken_either_stores_one_turn_or_is_lost(db_url: str) -> None:
    """Whether an expired claim nobody has taken can still finish is not stated; either way, never two replies."""

    async def go() -> None:
        async with rig(db_url) as r:
            claim = await r.begin()
            await r.expire(claim)
            try:
                await r.inflight.finish(claim, NewTurn("ashley", "mine"))
            except ClaimLost:
                pass
            assert len(await r.hers()) <= 1
            assert await r.rows() == (1 if not await r.hers() else 0)

    run(go())


def test_finish_into_a_closed_conversation_keeps_the_work_for_drop(db_url: str) -> None:
    async def go() -> None:
        async with rig(db_url) as r:
            conv = await r.conversations.for_thread(r.home, "cmd", "command", [r.who])
            said = await r.conversations.add_turn(conv.id, NewTurn("person", "hi", r.who))
            claim = await r.inflight.begin(conv.id, said.id, "cp")
            place_before_now(db_url, conv.id, 100_000)
            with pytest.raises(ConversationClosed):
                await r.inflight.finish(claim, NewTurn("ashley", "late"))
            assert await r.hers() == []
            assert await r.rows() == 1
            await r.inflight.drop(claim)
            assert await r.rows() == 0

    run(go())


def test_finish_with_a_turn_conversations_refuses_is_a_value_error_and_keeps_the_work(db_url: str) -> None:
    async def go() -> None:
        async with rig(db_url) as r:
            claim = await r.begin()
            with pytest.raises(ValueError):
                await r.inflight.finish(claim, NewTurn("ashley", "   "))
            assert await r.hers() == [] and await r.rows() == 1
            await r.inflight.finish(claim, NewTurn("ashley", "fine"))
            assert await r.hers() == ["fine"]

    run(go())


def test_drop_removes_the_work_and_stores_no_turn(db_url: str) -> None:
    async def go() -> None:
        async with rig(db_url) as r:
            claim = await r.begin()
            await r.inflight.drop(claim)
            assert await r.rows() == 0 and await r.hers() == []
            await r.expire_all()
            assert await r.inflight.orphaned(10) == []

    run(go())


def test_drop_twice_and_drop_of_nothing_are_quiet(db_url: str) -> None:
    async def go() -> None:
        async with rig(db_url) as r:
            claim = await r.begin()
            await r.inflight.drop(claim)
            await r.inflight.drop(claim)

    run(go())


def test_drop_by_a_runner_that_lost_the_claim_leaves_the_new_runners_work(db_url: str) -> None:
    async def go() -> None:
        async with rig(db_url) as r:
            old = await r.begin("mine")
            await r.expire(old)
            [taken] = await r.inflight.orphaned(10)
            await r.inflight.drop(old)
            assert await r.rows() == 1
            await r.inflight.finish(taken.claim, NewTurn("ashley", "ok"))
            assert await r.hers() == ["ok"]

    run(go())


def test_work_for_the_same_turn_can_begin_again_once_finished(db_url: str) -> None:
    async def go() -> None:
        async with rig(db_url) as r:
            conv_id, said_id = await r.said()
            first = await r.inflight.begin(conv_id, said_id, "a")
            await r.inflight.drop(first)
            second = await r.inflight.begin(conv_id, said_id, "b")
            assert second.holder != first.holder

    run(go())


def test_drop_says_no_work_remains_when_it_deleted_the_work_or_there_was_none(db_url: str) -> None:
    async def go() -> None:
        async with rig(db_url) as r:
            claim = await r.begin()
            assert await r.inflight.drop(claim) is True
            assert await r.inflight.drop(claim) is True

    run(go())


def test_drop_says_work_remains_when_another_runner_holds_it(db_url: str) -> None:
    async def go() -> None:
        async with rig(db_url) as r:
            old = await r.begin()
            await r.expire(old)
            [taken] = await r.inflight.orphaned(10)
            assert await r.inflight.drop(old) is False
            assert await r.rows() == 1
            assert await r.inflight.drop(taken.claim) is True

    run(go())
