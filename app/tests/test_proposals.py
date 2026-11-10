"""`Proposals` as one store: every payload kind comes back as it went in, a person has one pending proposal per
conversation and topic so a reminder and a house change proposed in one conversation are kept and taken apart, and
`propose` drops only its own topic's old ones."""

from datetime import UTC, datetime, timedelta

import pytest
from ashley.home_assistant.change import Change
from ashley.senses.deposit_rule import DepositRule
from ashley.senses.postgres_proposals import PostgresProposals
from ashley.senses.proposal_payloads import (HOUSE, REMINDERS, HouseChange, MoneyRule, Payload, ReminderChange,
                                             ReminderSchedule)
from ashley.senses.proposals import Proposal, ProposalRefused
from ashley.senses.repeat import Repeat
from ashley.senses.wakes import Reminder
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import household, person, run, scalar
from ashley.db.pool import PoolDatabase

TTL = 600.0
RULE = DepositRule("acct-1", "Checking", 100_000, "Acme", "contains")
CHANGE = HouseChange(Change("perform", "action", "homeassistant.stop", {"n": [1, {"b": None}]}, ("light.a",)), "stop the house")
GIVEN = datetime(2026, 11, 3, 15, 0, 0, 123456, tzinfo=UTC)


def now() -> datetime:
    return datetime.now(UTC)


def reminder(home: int, who: int, brief: str = "turn the lamp on", repeat: Repeat | None = None,
             tools: tuple[str, ...] | None = None) -> Reminder:
    return Reminder(home, who, who, brief, now() + timedelta(hours=1), repeat, None, "quiet", tools)


async def stored(url: str) -> tuple[PostgresProposals, int, int, PoolDatabase]:
    db = PoolDatabase(url, connect_timeout_s=5.0)
    await db.open()
    home = household(url)
    return PostgresProposals(db), home, person(url, home, "Alana"), db


def test_every_kind_comes_back_as_it_went_in_with_the_turn_and_time_it_was_given(db_url: str) -> None:
    async def go() -> None:
        proposals, home, alana, db = await stored(db_url)
        try:
            repeat = Repeat("weekly", 1, datetime(2030, 1, 7, 9, 0), (0,))
            kinds: list[tuple[int, Payload]] = [
                (1, MoneyRule(reminder(home, alana, "move it"), RULE)),
                (2, ReminderSchedule(reminder(home, alana, repeat=repeat, tools=("lamp_on", "lamp_off")))),
                (3, ReminderChange(reminder(home, alana, "the edit"), 77))]
            for conversation, payload in kinds:
                await proposals.propose(Proposal(home, alana, conversation, 10, GIVEN, payload), 10**9)
                got = await proposals.take(alana, conversation, REMINDERS, 11, 10**9)
                assert got.payload == payload
                assert (got.household_id, got.made_by, got.conversation_id, got.turn_id, got.proposed_at) == (
                    home, alana, conversation, 10, GIVEN)
            await proposals.propose(Proposal(home, alana, 4, 10, GIVEN, CHANGE), 10**9)
            assert (await proposals.take(alana, 4, HOUSE, 11, 10**9)).payload == CHANGE
        finally:
            await db.close()

    run(go())


def test_a_reminder_and_a_house_change_in_one_conversation_are_kept_and_taken_apart(db_url: str) -> None:
    async def go() -> None:
        proposals, home, alana, db = await stored(db_url)
        try:
            await proposals.propose(Proposal(home, alana, 1, 10, now(), ReminderSchedule(reminder(home, alana))), TTL)
            await proposals.propose(Proposal(home, alana, 1, 11, now(), CHANGE), TTL)
            assert (await proposals.take(alana, 1, REMINDERS, 12, TTL)).turn_id == 10
            assert (await proposals.take(alana, 1, HOUSE, 12, TTL)).payload == CHANGE
            with pytest.raises(ProposalRefused) as gone:
                await proposals.take(alana, 1, HOUSE, 13, TTL)
            assert gone.value.reason == "none"
        finally:
            await db.close()

    run(go())


def test_a_newer_proposal_replaces_the_earlier_of_its_own_topic_only(db_url: str) -> None:
    async def go() -> None:
        proposals, home, alana, db = await stored(db_url)
        try:
            await proposals.propose(Proposal(home, alana, 1, 10, now(), CHANGE), TTL)
            await proposals.propose(Proposal(home, alana, 1, 10, now(), ReminderSchedule(reminder(home, alana, "FIRST"))), TTL)
            await proposals.propose(Proposal(home, alana, 1, 11, now(), MoneyRule(reminder(home, alana, "SECOND"), RULE)), TTL)
            assert scalar(db_url, "SELECT array_agg(topic ORDER BY topic) FROM proposals") == ["house", "reminder"]
            got = await proposals.pending(alana, 1, REMINDERS)
            assert got is not None and isinstance(got.payload, MoneyRule) and got.payload.reminder.brief == "SECOND"
        finally:
            await db.close()

    run(go())


def test_proposing_drops_only_its_own_topics_old_proposals(db_url: str) -> None:
    async def go() -> None:
        proposals, home, alana, db = await stored(db_url)
        try:
            await proposals.propose(Proposal(home, alana, 1, 10, now() - timedelta(days=3), CHANGE), 10**9)
            await proposals.propose(Proposal(home, alana, 2, 10, now() - timedelta(days=3), ReminderSchedule(reminder(home, alana))), 10**9)
            await proposals.propose(Proposal(home, alana, 3, 10, now(), ReminderSchedule(reminder(home, alana))), TTL)
            assert scalar(db_url, "SELECT array_agg(conversation_id ORDER BY conversation_id) FROM proposals") == [1, 3]
        finally:
            await db.close()

    run(go())
