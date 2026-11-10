"""When a proposal may be taken: `proposal_gate.gate` and `proposals.refusal` over turn ids and the age of the proposal,
for a reminder to schedule also its first time having come, and `Proposals.take` refusing by them."""

from datetime import timedelta

import pytest
from ashley.senses.proposal_gate import gate
from ashley.senses.proposal_payloads import HOUSE, REMINDERS, MoneyRule, ReminderChange
from ashley.senses.proposals import ProposalRefused, refusal
from contract.conversations_support import run
from proposals_blind_support import HOUR, NOW, TTL, clock, edit, house_change, money, proposal, reminder, schedule, store

THEN = NOW


def test_gate_lets_a_later_turn_within_the_limit_through() -> None:
    assert gate(10, THEN, 11, THEN + timedelta(seconds=30), 600.0) is None
    assert gate(10, THEN, 500, THEN + timedelta(seconds=599), 600.0) is None


def test_gate_refuses_the_same_turn_and_an_earlier_one() -> None:
    assert gate(10, THEN, 10, THEN + timedelta(seconds=1), 600.0) == "same_turn"
    assert gate(10, THEN, 9, THEN + timedelta(seconds=1), 600.0) == "same_turn"


def test_gate_refuses_a_later_turn_past_the_limit() -> None:
    assert gate(10, THEN, 11, THEN + timedelta(seconds=601), 600.0) == "expired"
    assert gate(10, THEN, 11, THEN + timedelta(days=3), 600.0) == "expired"


def test_a_proposal_exactly_as_old_as_the_limit_is_still_within_it() -> None:
    assert gate(10, THEN, 11, THEN + timedelta(seconds=600), 600.0) is None


def test_the_limit_is_the_callers() -> None:
    at = THEN + timedelta(seconds=100)
    assert gate(10, THEN, 11, at, 1000.0) is None
    assert gate(10, THEN, 11, at, 50.0) == "expired"


def test_refusal_follows_the_gate_for_every_kind() -> None:
    for payload in (money(1, 1), edit(1, 1), house_change(), schedule(1, 1)):
        made = proposal(payload, 1, 1, 1, 10, THEN)
        assert refusal(made, 11, THEN + timedelta(seconds=5), 600.0) is None
        assert refusal(made, 10, THEN + timedelta(seconds=5), 600.0) == "same_turn"
        assert refusal(made, 11, THEN + timedelta(seconds=700), 600.0) == "expired"


def test_a_reminder_to_schedule_is_refused_once_its_first_time_has_come() -> None:
    due = THEN + timedelta(hours=1)
    made = proposal(schedule(1, 1, due_at=due), 1, 1, 1, 10, THEN)
    assert refusal(made, 11, due - timedelta(seconds=5), 7200.0) is None
    assert refusal(made, 11, due + timedelta(seconds=5), 7200.0) == "expired"


def test_a_money_rule_a_change_and_a_house_change_are_not_refused_for_their_reminders_time() -> None:
    past = THEN - timedelta(days=5)
    for payload in (MoneyRule(reminder(1, 1, due_at=past), money(1, 1).rule), ReminderChange(reminder(1, 1, due_at=past), 3),
                    house_change()):
        made = proposal(payload, 1, 1, 1, 10, THEN)
        assert refusal(made, 11, THEN + timedelta(seconds=5), 600.0) is None


def test_take_refuses_the_turn_it_was_proposed_in_and_leaves_it_to_be_taken_later(db_url: str) -> None:
    async def go() -> None:
        async with store(db_url) as s:
            made = proposal(house_change(), s.house, s.alana, 1, 10)
            await s.store.propose(made, TTL)
            for turn in (10, 9):
                with pytest.raises(ProposalRefused) as same:
                    await s.store.take(s.alana, 1, HOUSE, turn, TTL)
                assert same.value.reason == "same_turn"
            assert await s.store.pending(s.alana, 1, HOUSE) == made
            assert await s.store.take(s.alana, 1, HOUSE, 11, TTL) == made

    run(go())


def test_take_refuses_one_older_than_ttl(db_url: str) -> None:
    async def go() -> None:
        async with store(db_url) as s:
            await s.store.propose(proposal(house_change(), s.house, s.alana, 1, 10, clock() - timedelta(seconds=300)), HOUR)
            with pytest.raises(ProposalRefused) as old:
                await s.store.take(s.alana, 1, HOUSE, 11, 100.0)
            assert old.value.reason == "expired"
            with pytest.raises(ProposalRefused) as again:
                await s.store.take(s.alana, 1, HOUSE, 12, 100.0)
            assert again.value.reason in ("expired", "none")

    run(go())


def test_take_within_ttl_succeeds_where_a_shorter_ttl_refused(db_url: str) -> None:
    async def go() -> None:
        async with store(db_url) as s:
            made = proposal(house_change(), s.house, s.alana, 1, 10, clock() - timedelta(seconds=300))
            await s.store.propose(made, HOUR)
            assert await s.store.take(s.alana, 1, HOUSE, 11, 1000.0) == made

    run(go())


def test_take_refuses_a_reminder_to_schedule_whose_time_has_come(db_url: str) -> None:
    async def go() -> None:
        async with store(db_url) as s:
            gone = proposal(schedule(s.house, s.alana, due_at=clock() - timedelta(seconds=30)), s.house, s.alana, 1, 10,
                            clock() - timedelta(seconds=60))
            await s.store.propose(gone, TTL)
            with pytest.raises(ProposalRefused) as late:
                await s.store.take(s.alana, 1, REMINDERS, 11, TTL)
            assert late.value.reason == "expired"

    run(go())


def test_a_money_rule_is_taken_though_its_reminder_time_is_when_it_was_proposed(db_url: str) -> None:
    async def go() -> None:
        async with store(db_url) as s:
            made = proposal(money(s.house, s.alana), s.house, s.alana, 1, 10, clock() - timedelta(seconds=30))
            await s.store.propose(made, TTL)
            assert await s.store.take(s.alana, 1, REMINDERS, 11, TTL) == made

    run(go())
