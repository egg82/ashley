"""`InFlight.working`: the person turns of a conversation whose work is in flight, for the page to show her still on
them. Postgres is real."""

from ashley.conversations.model import NewTurn
from contract.conversations_support import run
from ifb_support import rig


def test_a_turn_with_work_is_working_until_her_answer_ends_it(db_url: str) -> None:
    async def go() -> None:
        async with rig(db_url) as r:
            claim = await r.begin()
            assert await r.inflight.working(claim.conversation_id) == frozenset({claim.said_id})
            await r.inflight.finish(claim, NewTurn("ashley", "Done.", answers=claim.said_id))
            assert await r.inflight.working(claim.conversation_id) == frozenset()

    run(go())


def test_work_kept_only_for_a_memory_act_after_her_answer_is_not_working(db_url: str) -> None:
    async def go() -> None:
        async with rig(db_url) as r:
            claim = await r.begin()
            await r.inflight.finish(claim, NewTurn("ashley", "Done.", answers=claim.said_id), lambda stored: "act")
            assert await r.rows() == 1
            assert await r.inflight.working(claim.conversation_id) == frozenset()

    run(go())


def test_work_in_another_conversation_is_not_this_ones(db_url: str) -> None:
    async def go() -> None:
        async with rig(db_url) as r:
            mine, other = await r.begin(thread="a"), await r.begin(thread="b")
            assert await r.inflight.working(mine.conversation_id) == frozenset({mine.said_id})
            assert await r.inflight.working(other.conversation_id) == frozenset({other.said_id})

    run(go())


def test_work_whose_claim_ran_out_is_still_working_until_resumed_and_ended(db_url: str) -> None:
    async def go() -> None:
        async with rig(db_url) as r:
            claim = await r.begin()
            await r.expire(claim)
            assert await r.inflight.working(claim.conversation_id) == frozenset({claim.said_id})
            (orphan,) = await r.inflight.orphaned(10)
            await r.inflight.drop(orphan.claim)
            assert await r.inflight.working(claim.conversation_id) == frozenset()

    run(go())


def test_a_conversation_with_no_work_has_none_working(db_url: str) -> None:
    async def go() -> None:
        async with rig(db_url) as r:
            conv_id, _ = await r.said()
            assert await r.inflight.working(conv_id) == frozenset()

    run(go())
