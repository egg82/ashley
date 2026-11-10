"""A held proposal by its id: read back with the id it was stored under, taken only by the person it was held for, and
refused with the reason (gone, expired, not theirs, not from a later turn); one the person's next hold replaced is gone,
and what the page is told it can agree to (`waiting`) is that person's own unexpired proposal only."""

from datetime import timedelta

import pytest
from ashley.channels.agree import waiting
from ashley.senses.proposal_payloads import OUTSIDE
from ashley.senses.proposals import ProposalRefused
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template, run
from agree_support import HELD, world

TTL = 600.0


def test_a_proposal_is_found_by_the_id_it_was_stored_under(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            proposal = await w.hold()
            found = await w.proposals.find(proposal, OUTSIDE)
            assert found is not None and found.id == proposal and found.made_by == w.alana
            assert found.payload.calls == HELD
            assert await w.proposals.find(proposal + 1, OUTSIDE) is None
            pending = await w.proposals.pending(w.alana, 0, OUTSIDE)
            assert pending is not None and pending.id == proposal
    run(go())


def test_taking_by_id_consumes_it_once(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            proposal = await w.hold()
            taken = await w.proposals.take_by_id(proposal, OUTSIDE, w.alana, 10**9, TTL)
            assert taken.payload.calls == HELD
            with pytest.raises(ProposalRefused) as again:
                await w.proposals.take_by_id(proposal, OUTSIDE, w.alana, 10**9, TTL)
            assert again.value.reason == "none"
    run(go())


@pytest.mark.parametrize(("case", "reason"), [("someone_else", "not_yours"), ("lapsed", "expired"), ("same_turn", "same_turn")])
def test_a_refused_take_names_why_and_leaves_the_proposal(db_url: str, case: str, reason: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            proposal = await w.hold(age=timedelta(seconds=2 * TTL) if case == "lapsed" else timedelta(0))
            found = await w.proposals.find(proposal, OUTSIDE)
            assert found is not None
            by, turn = (w.sam, 10**9) if case == "someone_else" else (w.alana, found.turn_id if case == "same_turn" else 10**9)
            with pytest.raises(ProposalRefused) as refused:
                await w.proposals.take_by_id(proposal, OUTSIDE, by, turn, TTL)
            assert refused.value.reason == reason
            assert await w.proposals.find(proposal, OUTSIDE) is not None
    run(go())


def test_a_later_hold_replaces_the_earlier_proposal_so_its_id_is_gone(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            first, second = await w.hold(), await w.hold()
            assert first != second
            assert await w.proposals.find(first, OUTSIDE) is None
            with pytest.raises(ProposalRefused):
                await w.proposals.take_by_id(first, OUTSIDE, w.alana, 10**9, TTL)
            assert await w.proposals.find(second, OUTSIDE) is not None
    run(go())


def test_waiting_is_the_persons_own_unexpired_proposal_and_the_turn_it_was_held_in(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            assert await waiting(w.alana, w.home) is None
            proposal = await w.hold()
            held = await w.proposals.find(proposal, OUTSIDE)
            assert held is not None
            assert await waiting(w.alana, w.home) == (proposal, held.turn_id)
            assert await waiting(w.sam, w.home) is None
            assert await waiting(w.alana, w.home + 1) is None
            await w.proposals.take_by_id(proposal, OUTSIDE, w.alana, 10**9, TTL)
            assert await waiting(w.alana, w.home) is None
    run(go())


def test_a_lapsed_proposal_is_not_offered_to_agree(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            await w.hold(age=timedelta(days=3))
            assert await waiting(w.alana, w.home) is None
    run(go())
