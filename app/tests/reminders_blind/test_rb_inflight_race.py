"""`InFlight.begin` racing a finish never yields two answers for one turn."""

import asyncio

import pytest
from ashley.conversations.inflight import ClaimLost, InFlight
from ashley.conversations.model import NewTurn
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template, run
from contract.conversations_support import household, person
from rb_flight import Rig, rig

ROUNDS = 25


async def work(r: Rig, inflight: InFlight, conversation_id: int, said_id: int, text: str) -> str:
    try:
        claim = await inflight.begin(conversation_id, said_id, "cp")
    except ValueError:
        return "refused"
    try:
        await inflight.finish(claim, NewTurn("ashley", text, answers=said_id))
    except ClaimLost:
        return "lost"
    return "answered"


def test_two_runners_beginning_and_finishing_one_turn_give_one_answer(db_url: str) -> None:
    async def go() -> None:
        house = household(db_url)
        who = person(db_url, house)
        async with rig(db_url, house, who) as a, rig(db_url, house, who) as b:
            for n in range(ROUNDS):
                conv, said = await a.said(f"t{n}")
                got = await asyncio.gather(work(a, a.inflight, conv, said, "one"), work(b, b.inflight, conv, said, "two"))
                assert got.count("answered") == 1, got
            assert len(a.hers()) == ROUNDS and a.rows() == 0

    run(go())


def test_a_begin_racing_a_finish_that_is_already_underway_is_refused_or_never_finishes_a_second_answer(db_url: str) -> None:
    async def go() -> None:
        house = household(db_url)
        who = person(db_url, house)
        async with rig(db_url, house, who) as a, rig(db_url, house, who) as b:
            for n in range(ROUNDS):
                conv, said = await a.said(f"s{n}")
                claim = await a.inflight.begin(conv, said, "cp")
                late = asyncio.create_task(work(b, b.inflight, conv, said, "late"))
                first = asyncio.create_task(a.inflight.finish(claim, NewTurn("ashley", "first", answers=said)))
                await first
                assert await late in ("refused", "lost")
            assert len(a.hers()) == ROUNDS and a.rows() == 0

    run(go())


def test_a_begin_after_her_answer_is_stored_is_refused_and_leaves_no_work(db_url: str) -> None:
    async def go() -> None:
        async with rig(db_url) as r:
            conv, said = await r.said("t")
            claim = await r.inflight.begin(conv, said, "cp")
            await r.inflight.finish(claim, NewTurn("ashley", "done", answers=said))
            with pytest.raises(ValueError):
                await r.inflight.begin(conv, said, "cp")
            assert r.rows() == 0 and r.hers() == ["done"]

    run(go())
