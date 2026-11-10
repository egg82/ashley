"""The Postgres store keeps one pending `OUTSIDE` proposal per person, found from any conversation; the other topics stay
per conversation; the held calls come back as stored."""

from datetime import UTC, datetime

from ashley.senses.proposal_payloads import HOUSE, OUTSIDE, HeldCall, HeldCalls, HouseChange
from ashley.senses.proposals import Proposal, ProposalRefused
from contract.conversations_support import run
from ashley.home_assistant.change import Change
from outside_ask_support import store

import pytest


def held(*tools: str) -> HeldCalls:
    return HeldCalls(tuple(HeldCall(t, {"a": [1, "x"]}, f"{t} (a: [1, \"x\"])") for t in tools))


def test_a_person_has_one_pending_outside_proposal_found_from_any_conversation(db_url: str) -> None:
    async def go() -> None:
        async with store(db_url) as s:
            now = datetime.now(UTC)
            first = Proposal(s.house, s.alana, 5, 10, now, held("lamp"))
            second = Proposal(s.house, s.alana, 6, 12, now, held("garage", "lamp"))
            await s.store.propose(first, 600)
            assert await s.store.pending(s.alana, 99, OUTSIDE) == first
            await s.store.propose(second, 600)
            assert await s.store.pending(s.alana, 5, OUTSIDE) == second
            assert await s.store.pending(s.sam, 6, OUTSIDE) is None
            with pytest.raises(ProposalRefused) as same:
                await s.store.take(s.alana, 77, OUTSIDE, 12, 600)
            assert same.value.reason == "same_turn"
            assert await s.store.take(s.alana, 77, OUTSIDE, 13, 600) == second
            assert await s.store.pending(s.alana, 6, OUTSIDE) is None

    run(go())


def test_a_conversation_scoped_topic_stays_per_conversation(db_url: str) -> None:
    async def go() -> None:
        async with store(db_url) as s:
            now = datetime.now(UTC)
            change = HouseChange(Change("delete", "automation", "x", {}, ()), "delete x")
            await s.store.propose(Proposal(s.house, s.alana, 5, 10, now, change), 600)
            await s.store.propose(Proposal(s.house, s.alana, 6, 11, now, change), 600)
            assert (await s.store.pending(s.alana, 5, HOUSE)) is not None
            assert (await s.store.pending(s.alana, 7, HOUSE)) is None
            await s.store.propose(Proposal(s.house, s.alana, 5, 14, now, held("lamp")), 600)
            assert (await s.store.pending(s.alana, 5, HOUSE)) is not None

    run(go())


def test_an_outside_proposal_with_no_call_is_refused(db_url: str) -> None:
    async def go() -> None:
        async with store(db_url) as s:
            with pytest.raises(ValueError):
                await s.store.propose(Proposal(s.house, s.alana, 5, 10, datetime.now(UTC), HeldCalls(())), 600)

    run(go())
