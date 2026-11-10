"""Pins on the proposal store's edges that the suites around it left open: the latest of several stored rows is the one
pending (a second proposer racing the replace can leave two), a brief of exactly `MAX_BRIEF` and exactly `MAX_TOOLS`
tools are kept while one more of either is refused, and the person a reminder is for is kept apart from who made it."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
from ashley.db.pool import PoolDatabase
from ashley.home_assistant.change import Change
from ashley.senses.postgres_proposals import PostgresProposals
from ashley.senses.proposal_payloads import HOUSE, REMINDERS, HouseChange, Payload, ReminderSchedule, encode
from ashley.senses.proposals import Proposal
from ashley.senses.wakes import MAX_BRIEF, MAX_TOOLS, Reminder
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import household, person, run, scalar
from psycopg.types.json import Jsonb

TTL = 3600.0


def now() -> datetime:
    return datetime.now(UTC)


@asynccontextmanager
async def store(url: str) -> AsyncGenerator[tuple[PostgresProposals, int, int, int]]:
    db = PoolDatabase(url, connect_timeout_s=5.0)
    await db.open()
    home = household(url)
    try:
        yield PostgresProposals(db), home, person(url, home, "Alana"), person(url, home, "Sam")
    finally:
        await db.close()


def reminder(home: int, who: int, by: int, brief: str = "turn the lamp on", tools: tuple[str, ...] | None = None) -> Reminder:
    return Reminder(home, who, by, brief, now() + timedelta(hours=1), None, None, "phone", tools)


def schedule(home: int, who: int, by: int, brief: str = "turn the lamp on", tools: tuple[str, ...] | None = None) -> Proposal[Payload]:
    return Proposal(home, by, 1, 10, now(), ReminderSchedule(reminder(home, who, by, brief, tools)))


def insert(url: str, home: int, made_by: int, payload: Payload) -> None:
    topic, stored = encode(payload)
    scalar(url, "INSERT INTO proposals (household_id, made_by, conversation_id, turn_id, topic, payload, created_at) "
                "VALUES (%s, %s, 1, 10, %s, %s, now()) RETURNING id", (home, made_by, topic, Jsonb(stored)))


def test_the_latest_of_two_stored_reminder_proposals_is_the_pending_one(db_url: str) -> None:
    async def go() -> None:
        async with store(db_url) as (proposals, home, alana, _sam):
            for brief in ("OLD", "NEW"):
                insert(db_url, home, alana, ReminderSchedule(reminder(home, alana, alana, brief)))
            found = await proposals.pending(alana, 1, REMINDERS)
            assert found is not None and found.payload.reminder.brief == "NEW"
            assert (await proposals.take(alana, 1, REMINDERS, 11, TTL)).payload.reminder.brief == "NEW"

    run(go())


def test_the_latest_of_two_stored_house_proposals_is_the_pending_one(db_url: str) -> None:
    async def go() -> None:
        async with store(db_url) as (proposals, home, alana, _sam):
            for summary in ("OLD", "NEW"):
                insert(db_url, home, alana, HouseChange(Change("delete", "area", "a"), summary))
            found = await proposals.pending(alana, 1, HOUSE)
            assert found is not None and found.payload.summary == "NEW"
            assert (await proposals.take(alana, 1, HOUSE, 11, TTL)).payload.summary == "NEW"

    run(go())


def test_a_brief_of_exactly_the_limit_and_exactly_the_most_tools_are_kept(db_url: str) -> None:
    async def go() -> None:
        async with store(db_url) as (proposals, home, alana, _sam):
            names = tuple(f"tool_{i}" for i in range(MAX_TOOLS))
            await proposals.propose(schedule(home, alana, alana, "x" * MAX_BRIEF, names), TTL)
            got = (await proposals.take(alana, 1, REMINDERS, 11, TTL)).payload.reminder
            assert got.brief == "x" * MAX_BRIEF and got.tools == names

    run(go())


def test_one_tool_more_than_the_most_is_refused_and_replaces_nothing(db_url: str) -> None:
    async def go() -> None:
        async with store(db_url) as (proposals, home, alana, _sam):
            await proposals.propose(schedule(home, alana, alana, "KEPT"), TTL)
            names = tuple(f"tool_{i}" for i in range(MAX_TOOLS + 1))
            with pytest.raises(ValueError):
                await proposals.propose(schedule(home, alana, alana, tools=names), TTL)
            found = await proposals.pending(alana, 1, REMINDERS)
            assert found is not None and found.payload.reminder.brief == "KEPT"

    run(go())


def test_the_person_a_reminder_is_for_is_kept_apart_from_who_made_it(db_url: str) -> None:
    async def go() -> None:
        async with store(db_url) as (proposals, home, alana, sam):
            await proposals.propose(schedule(home, sam, alana), TTL)
            got = (await proposals.take(alana, 1, REMINDERS, 11, TTL)).payload.reminder
            assert (got.person_id, got.made_by) == (sam, alana)

    run(go())


def test_a_house_proposal_keeps_its_household_apart_from_who_made_it(db_url: str) -> None:
    async def go() -> None:
        async with store(db_url) as (proposals, _home, alana, _sam):
            other = household(db_url, "second")
            await proposals.propose(Proposal(other, alana, 1, 10, now(), HouseChange(Change("delete", "area", "a"), "s")), TTL)
            got = await proposals.take(alana, 1, HOUSE, 11, TTL)
            assert (got.household_id, got.made_by) == (other, alana) and other != alana

    run(go())
