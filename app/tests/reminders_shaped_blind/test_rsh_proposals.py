"""`Proposals.propose`, `pending` and `take` on the reminders topic, and `refusal`: a proposal is taken once, only by whoever made it, in its own
conversation, from a later turn and within its time; a newer proposal replaces the older; one for a reminder is taken
only before its time."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from ashley.senses.deposit_rule import DepositRule
from ashley.senses.proposal_payloads import REMINDERS, MoneyRule, ReminderChange, ReminderPayload, ReminderSchedule
from ashley.senses.proposals import Proposal, ProposalRefused, refusal
from ashley.senses.repeat import Repeat
from ashley.senses.wakes import Reminder
from contract.conversations_support import run, scalar
from rsh_support import BRIEF, Home, home, now

TTL = 600.0


async def pending_brief(h: Home, who: int, conv: int) -> str | None:
    found = await h.proposals.pending(who, conv, REMINDERS)
    return None if found is None else found.payload.reminder.brief
RULE = DepositRule("acct-1", "RSH-Checking", 100_000, "Acme", "contains")


def payload_of(reminder: Reminder, rule: DepositRule | None, target: int | None) -> ReminderPayload:
    if rule is not None:
        return MoneyRule(reminder, rule)
    return ReminderSchedule(reminder) if target is None else ReminderChange(reminder, target)


def proposal(h: Home, conv: int = 1, turn: int = 10, who: int | None = None, brief: str = BRIEF, rule: DepositRule | None = None,
             target: int | None = None, age_s: float = 0.0, due_in_s: float = 3600.0, by: int | None = None,
             **more: object) -> Proposal[ReminderPayload]:
    at = now() - timedelta(seconds=age_s)
    reminder = replace(h.reminder(who=who, by=by, brief=brief, due_in_s=due_in_s), **more)
    return Proposal(h.house, reminder.made_by, conv, turn, at, payload_of(reminder, rule, target))


def test_a_proposal_taken_from_a_later_turn_comes_back_whole_and_is_consumed(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as h:
            sent = proposal(h, repeat=Repeat("weekly", 1, datetime(2030, 1, 7, 9, 0), (0,)), route="quiet", tools=("lamp_on",))
            assert isinstance(await h.proposals.propose(sent, TTL), int)
            got = await h.proposals.take(h.alana, 1, REMINDERS, 11, TTL)
            assert got.payload == sent.payload and isinstance(got.payload, ReminderSchedule)
            assert (got.conversation_id, got.turn_id) == (1, 10)
            with pytest.raises(ProposalRefused) as gone:
                await h.proposals.take(h.alana, 1, REMINDERS, 12, TTL)
            assert gone.value.reason == "none"
            assert await h.proposals.pending(h.alana, 1, REMINDERS) is None

    run(go())


def test_a_money_rule_and_an_edit_target_come_back_as_proposed(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as h:
            sent = proposal(h, 1, 10, rule=RULE)
            await h.proposals.propose(sent, TTL)
            assert (await h.proposals.take(h.alana, 1, REMINDERS, 11, TTL)).payload == sent.payload
            edit = proposal(h, 2, 10, target=77, brief="the edit")
            await h.proposals.propose(edit, TTL)
            got = (await h.proposals.take(h.alana, 2, REMINDERS, 11, TTL)).payload
            assert isinstance(got, ReminderChange) and (got.target, got.reminder.brief) == (77, "the edit")

    run(go())


def test_nothing_proposed_is_refused_as_none(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as h:
            with pytest.raises(ProposalRefused) as e:
                await h.proposals.take(h.alana, 1, REMINDERS, 11, TTL)
            assert e.value.reason == "none"
            assert await h.proposals.pending(h.alana, 1, REMINDERS) is None

    run(go())


@pytest.mark.parametrize("turn,reason", [(10, "same_turn"), (9, None), (3, None)])
def test_a_proposal_cannot_be_taken_in_the_turn_it_was_made_in_nor_an_earlier_one_and_stays_to_be_taken(
        db_url: str, turn: int, reason: str | None) -> None:
    async def go() -> None:
        async with home(db_url) as h:
            await h.proposals.propose(proposal(h, 1, 10), TTL)
            with pytest.raises(ProposalRefused) as e:
                await h.proposals.take(h.alana, 1, REMINDERS, turn, TTL)
            assert e.value.reason == (reason or e.value.reason) and e.value.reason != "none"
            assert (await h.proposals.pending(h.alana, 1, REMINDERS)) is not None
            assert (await h.proposals.take(h.alana, 1, REMINDERS, 11, TTL)).payload.reminder.brief == BRIEF

    run(go())


def test_a_proposal_older_than_its_time_is_refused_as_expired(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as h:
            await h.proposals.propose(proposal(h, 1, 10, age_s=TTL + 60), TTL)
            with pytest.raises(ProposalRefused) as e:
                await h.proposals.take(h.alana, 1, REMINDERS, 11, TTL)
            assert e.value.reason in ("expired", "none")

    run(go())


def test_a_proposal_within_its_time_is_taken(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as h:
            await h.proposals.propose(proposal(h, 1, 10, age_s=TTL - 120), TTL)
            assert (await h.proposals.take(h.alana, 1, REMINDERS, 11, TTL)).payload.reminder.brief == BRIEF

    run(go())


def test_a_reminder_proposed_for_a_time_that_has_come_cannot_be_taken(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as h:
            await h.proposals.propose(proposal(h, 1, 10, due_in_s=-5.0), 10_000.0)
            with pytest.raises(ProposalRefused) as e:
                await h.proposals.take(h.alana, 1, REMINDERS, 11, 10_000.0)
            assert e.value.reason == "expired"

    run(go())


def test_a_newer_proposal_replaces_the_older_and_only_it_can_be_taken(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as h:
            await h.proposals.propose(proposal(h, 1, 10, brief="FIRST"), TTL)
            await h.proposals.propose(proposal(h, 1, 11, brief="SECOND"), TTL)
            assert await pending_brief(h, h.alana, 1) == "SECOND"
            assert (await h.proposals.take(h.alana, 1, REMINDERS, 12, TTL)).payload.reminder.brief == "SECOND"
            with pytest.raises(ProposalRefused):
                await h.proposals.take(h.alana, 1, REMINDERS, 13, TTL)
            assert int(scalar(db_url, "SELECT count(*) FROM proposals")) == 0

    run(go())


@pytest.mark.parametrize("first_for,second_for", [("sam", "alana"), ("alana", "sam")])
def test_a_new_proposal_replaces_the_makers_earlier_one_whoever_either_was_for(db_url: str, first_for: str, second_for: str) -> None:
    async def go() -> None:
        async with home(db_url) as h:
            ids = {"sam": h.sam, "alana": h.alana}
            first = proposal(h, 1, 10, who=ids[first_for], by=h.alana, brief="FIRST")
            second = proposal(h, 1, 11, who=ids[second_for], by=h.alana, brief="SECOND")
            await h.proposals.propose(first, TTL)
            await h.proposals.propose(second, TTL)
            assert (await h.proposals.take(h.alana, 1, REMINDERS, 12, TTL)).payload.reminder.brief == "SECOND"
            assert int(scalar(db_url, "SELECT count(*) FROM proposals")) == 0

    run(go())


def test_a_proposal_is_for_its_person_and_its_conversation_alone(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as h:
            await h.proposals.propose(proposal(h, 1, 10, who=h.alana), TTL)
            await h.proposals.propose(proposal(h, 2, 10, who=h.sam, brief="SAMS"), TTL)
            for who, conv in ((h.sam, 1), (h.kim, 1), (h.alana, 3)):
                with pytest.raises(ProposalRefused):
                    await h.proposals.take(who, conv, REMINDERS, 11, TTL)
            assert (await h.proposals.take(h.alana, 1, REMINDERS, 11, TTL)).payload.reminder.brief == BRIEF
            assert (await h.proposals.pending(h.sam, 2, REMINDERS)) is not None

    run(go())


def test_a_new_proposal_of_one_person_does_not_replace_another_persons_in_the_same_conversation(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as h:
            await h.proposals.propose(proposal(h, 1, 10, brief="ALANAS"), TTL)
            await h.proposals.propose(proposal(h, 1, 10, who=h.sam, brief="SAMS"), TTL)
            assert (await h.proposals.take(h.alana, 1, REMINDERS, 11, TTL)).payload.reminder.brief == "ALANAS"

    run(go())


@pytest.mark.parametrize("brief", ["", "x" * 501, "a\x00b"])
def test_a_proposal_with_a_brief_outside_the_limits_raises_and_stores_nothing(db_url: str, brief: str) -> None:
    async def go() -> None:
        async with home(db_url) as h:
            with pytest.raises(ValueError):
                await h.proposals.propose(proposal(h, brief=brief), TTL)
            assert await h.proposals.pending(h.alana, 1, REMINDERS) is None

    run(go())


def test_a_repeat_on_a_money_rule_raises_and_keeps_the_proposal_it_would_have_replaced(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as h:
            await h.proposals.propose(proposal(h, 1, 10, brief="KEPT"), TTL)
            with pytest.raises(ValueError):
                await h.proposals.propose(proposal(h, 1, 11, rule=RULE, repeat=Repeat("daily", 1, datetime(2030, 1, 1, 9, 0))), TTL)
            assert await pending_brief(h, h.alana, 1) == "KEPT"

    run(go())


def test_a_proposal_older_than_its_time_is_dropped_when_another_is_stored(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as h:
            await h.proposals.propose(proposal(h, 1, 10, age_s=86_400.0 * 3), 10**9)
            await h.proposals.propose(proposal(h, 2, 10), TTL)
            assert int(scalar(db_url, "SELECT count(*) FROM proposals")) == 1

    run(go())


def test_two_takes_at_once_give_the_proposal_to_one(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as h:
            await h.proposals.propose(proposal(h, 1, 10), TTL)
            results = await asyncio.gather(*(h.proposals.take(h.alana, 1, REMINDERS, 11 + i, TTL) for i in range(6)), return_exceptions=True)
            assert sum(isinstance(r, Proposal) for r in results) == 1
            assert sum(isinstance(r, ProposalRefused) for r in results) == 5

    run(go())


T0 = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)


def made(rule: DepositRule | None, due_in_s: float, target: int | None = None) -> Proposal[ReminderPayload]:
    reminder = replace(Reminder(1, 1, 1, BRIEF, T0, None), due_at=T0 + timedelta(seconds=due_in_s))
    return Proposal(1, 1, 1, 10, T0, payload_of(reminder, rule, target))


@pytest.mark.parametrize("turn,now_s,ttl,want", [
    (11, 10.0, 600.0, None), (10, 10.0, 600.0, "same_turn"), (11, 601.0, 600.0, "expired"), (11, 600.0, 600.0, None),
    (11, 0.0, 600.0, None), (50, 100.0, 600.0, None)])
def test_refusal_names_why_a_proposal_for_a_reminder_cannot_be_taken_now(turn: int, now_s: float, ttl: float, want: str | None) -> None:
    assert refusal(made(None, 7200.0), turn, T0 + timedelta(seconds=now_s), ttl) == want


def test_refusal_of_a_reminder_for_a_time_that_has_come_is_expired_whatever_the_time_left() -> None:
    assert refusal(made(None, 30.0), 11, T0 + timedelta(seconds=60), 600.0) == "expired"
    assert refusal(made(None, 30.0), 11, T0 + timedelta(seconds=10), 600.0) is None


def test_a_reminder_proposed_for_exactly_now_cannot_be_taken() -> None:
    assert refusal(made(None, 30.0), 11, T0 + timedelta(seconds=30), 600.0) == "expired"


def test_a_proposed_change_to_a_reminder_is_not_bound_to_a_time_it_would_fire() -> None:
    edit = made(None, 30.0, target=5)
    assert refusal(edit, 11, T0 + timedelta(seconds=300), 600.0) is None
    assert refusal(edit, 11, T0 + timedelta(seconds=601), 600.0) == "expired"


def test_a_money_rule_has_no_time_of_its_own_to_come_before() -> None:
    assert refusal(made(RULE, 0.0), 11, T0 + timedelta(seconds=60), 600.0) is None
    assert refusal(made(RULE, 0.0), 10, T0 + timedelta(seconds=60), 600.0) == "same_turn"
    assert refusal(made(RULE, 0.0), 11, T0 + timedelta(seconds=601), 600.0) == "expired"
