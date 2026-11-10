"""Proposals under concurrent callers: of two takes at once one wins, and two proposals for one person, conversation and
topic made at once leave exactly one, the later."""

import asyncio

from ashley.senses.proposal_payloads import HOUSE, REMINDERS, HouseChange
from ashley.senses.proposals import Proposal, ProposalRefused
from contract.conversations_support import gather_settled, holding, run, scalar
from proposals_blind_support import TTL, Store, await_waiters, house_change, proposal, schedule, store


async def rows(s: Store) -> int:
    return int(scalar(s.url, "SELECT count(*) FROM proposals", ()))


def test_of_many_takes_at_once_exactly_one_wins(db_url: str) -> None:
    async def go() -> None:
        async with store(db_url) as s:
            made = proposal(house_change(), s.house, s.alana, 1, 10)
            await s.store.propose(made, TTL)
            got = await gather_settled(*[s.store.take(s.alana, 1, HOUSE, 11, TTL) for _ in range(8)])
            won = [g for g in got if not isinstance(g, BaseException)]
            lost = [g for g in got if isinstance(g, ProposalRefused)]
            assert won == [made] and len(lost) == 7 and {g.reason for g in lost} == {"none"}
            assert await s.store.pending(s.alana, 1, HOUSE) is None

    run(go())


def test_takes_held_at_a_row_lock_still_give_one_winner(db_url: str) -> None:
    async def go() -> None:
        async with store(db_url) as s:
            await s.store.propose(proposal(house_change(), s.house, s.alana, 1, 10), TTL)
            async with holding(db_url, "SELECT * FROM proposals FOR UPDATE", ()):
                calls = asyncio.gather(*[s.store.take(s.alana, 1, HOUSE, 11, TTL) for _ in range(3)], return_exceptions=True)
                await await_waiters(db_url, 2)
            got = await calls
            assert sum(isinstance(g, Proposal) for g in got) == 1
            assert sum(isinstance(g, ProposalRefused) for g in got) == 2

    run(go())


def test_takes_of_different_people_do_not_disturb_each_other(db_url: str) -> None:
    async def go() -> None:
        async with store(db_url) as s:
            for who in (s.alana, s.sam):
                await s.store.propose(proposal(schedule(s.house, who), s.house, who, 1, 10), TTL)
            got = await gather_settled(s.store.take(s.alana, 1, REMINDERS, 11, TTL), s.store.take(s.sam, 1, REMINDERS, 11, TTL))
            assert all(isinstance(g, Proposal) for g in got)
            assert await rows(s) == 0

    run(go())


def test_proposals_of_different_people_at_once_all_survive(db_url: str) -> None:
    async def go() -> None:
        async with store(db_url) as s:
            await gather_settled(*[s.store.propose(proposal(schedule(s.house, w), s.house, w, c, 10), TTL)
                                   for w in (s.alana, s.sam) for c in (1, 2, 3)])
            assert await rows(s) == 6

    run(go())


async def raced(s: Store) -> tuple[Proposal[HouseChange], Proposal[HouseChange], int, int]:
    """Two proposals for one key, made at once while a third, earlier one is locked, so both reach the replacing together."""
    await s.store.propose(proposal(house_change("old", "old"), s.house, s.alana, 1, 5), TTL)
    first = proposal(house_change("first", "a"), s.house, s.alana, 1, 10)
    second = proposal(house_change("second", "b"), s.house, s.alana, 1, 11)
    async with holding(s.url, "SELECT * FROM proposals FOR UPDATE", ()):
        calls = asyncio.gather(s.store.propose(first, TTL), s.store.propose(second, TTL))
        await await_waiters(s.url, 2)
    one, two = await calls
    return first, second, one, two


def test_of_two_proposals_made_at_once_for_one_key_the_later_is_the_one_that_can_be_taken(db_url: str) -> None:
    async def go() -> None:
        async with store(db_url) as s:
            first, second, one, two = await raced(s)
            later = first if one > two else second
            assert await s.store.pending(s.alana, 1, HOUSE) == later

    run(go())


def test_two_proposals_made_at_once_for_one_key_leave_exactly_one(db_url: str) -> None:
    async def go() -> None:
        async with store(db_url) as s:
            await raced(s)
            assert await rows(s) == 1

    run(go())


def test_nothing_is_left_to_take_after_the_later_of_two_racing_proposals_is_taken(db_url: str) -> None:
    async def go() -> None:
        async with store(db_url) as s:
            await raced(s)
            await s.store.take(s.alana, 1, HOUSE, 20, TTL)
            assert await s.store.pending(s.alana, 1, HOUSE) is None

    run(go())
