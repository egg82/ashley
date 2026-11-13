"""A standing errand in the wakes store and the reminder tools, over a real database and the real skills: `remind` with
`method` and a repeat stores a repeating reminder naming the household's kind of work, and each next occurrence
carries it on; a method that does not repeat, has an end, or names no kind with a method is refused before anything
is stored; a change keeps the method and cannot stop the repeat; a proposal keeps the method."""

import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
from ashley import services
from ashley.db.pool import PoolDatabase
from ashley.senses.proposal_payloads import REMINDERS, ReminderSchedule, encode
from ashley.senses.repeat import Repeat
from ashley.senses.wakes import Reminder
from ashley.skills import config, seeds
from ashley.skills.postgres import PostgresSkills
from ashley.skills.skills import Skills
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import run, scalar
from test_reminder_turn import BRIEF, World, world
from test_reminders_shaped import body, call, tomorrow_at, tools_for

DAILY = {"repeat": "daily"}


@asynccontextmanager
async def skilled(url: str) -> AsyncGenerator[World]:
    """The reminder world with the real skills, whose seeds give every household a `research` method."""
    db = PoolDatabase(url, connect_timeout_s=5.0)
    await db.open()
    loaded = config.load()
    services.register(Skills, PostgresSkills(db, loaded, seeds.load(loaded)))
    try:
        async with world(url) as w:
            yield w
    finally:
        services.unregister(Skills)
        await db.close()


def standing(w: World, method: str = "research", repeat: Repeat | None = None) -> Reminder:
    due = datetime.now(UTC) - timedelta(seconds=1)
    return Reminder(w.home, w.alana, w.alana, BRIEF, due,
                    repeat or Repeat("daily", 1, due.astimezone(UTC).replace(tzinfo=None)), method=method)


def methods(url: str) -> list[object]:
    got = scalar(url, "SELECT coalesce(json_agg(method ORDER BY id), '[]') FROM wakes")
    return list(got)


def test_remind_with_a_method_and_a_repeat_stores_a_standing_errand_and_lists_its_method(db_url: str) -> None:
    async def go() -> None:
        async with skilled(db_url) as w:
            made = body(await call(tools_for(w), "remind", {"for": "Alana", "at": tomorrow_at(8), **DAILY,
                                                            "what": "look for new listings", "method": "research"}))
            (listed,) = await w.wakes.reminders(w.home, w.alana)
            assert listed.id == made["id"] and listed.reminder.method == "research"
            assert listed.reminder.repeat is not None and listed.reminder.ends_at is None
            assert '"method": "research"' in json.dumps(body(await call(tools_for(w), "reminders", {})))
    run(go())


@pytest.mark.parametrize("extra", [{}, {"errand_hours": 2}, {**DAILY, "errand_hours": 2}])
def test_a_method_without_a_repeat_or_with_an_end_is_refused_and_nothing_is_stored(db_url: str,
                                                                                   extra: dict[str, object]) -> None:
    async def go() -> None:
        async with skilled(db_url) as w:
            got = await call(tools_for(w), "remind", {"for": "Alana", "at": tomorrow_at(8), "what": "x",
                                                      "method": "research", **extra})
            assert got.content.startswith("bad_arguments") and "repeat" in got.content, got.content
            assert methods(db_url) == []
    run(go())


def test_a_method_naming_no_kind_of_the_households_is_refused_naming_the_kinds_it_has(db_url: str) -> None:
    async def go() -> None:
        async with skilled(db_url) as w:
            got = await call(tools_for(w), "remind", {"for": "Alana", "at": tomorrow_at(8), **DAILY, "what": "x",
                                                      "method": "gardening"})
            assert got.content.startswith("bad_arguments") and "research" in got.content and "writing" in got.content
            assert methods(db_url) == []
    run(go())


def test_the_store_refuses_a_standing_errand_that_does_not_repeat_or_ends(db_url: str) -> None:
    async def go() -> None:
        async with skilled(db_url) as w:
            s = standing(w)
            for bad in (Reminder(w.home, w.alana, w.alana, BRIEF, s.due_at, None, method="research"),
                        Reminder(w.home, w.alana, w.alana, BRIEF, s.due_at, s.repeat, method="research",
                                 ends_at=s.due_at + timedelta(hours=1))):
                with pytest.raises(ValueError):
                    await w.wakes.schedule(bad)
            assert methods(db_url) == []
    run(go())


def test_the_table_itself_refuses_a_method_on_a_reminder_that_does_not_repeat(db_url: str) -> None:
    async def go() -> None:
        async with skilled(db_url) as w:
            plain = await w.remind()
            with pytest.raises(Exception, match="wakes_standing_errand"):
                scalar(db_url, f"WITH u AS (UPDATE wakes SET method = 'research' WHERE id = {plain} RETURNING 1) "
                               "SELECT count(*) FROM u")
            assert methods(db_url) == [None]
    run(go())


def test_each_next_occurrence_carries_the_method_on(db_url: str) -> None:
    async def go() -> None:
        async with skilled(db_url) as w:
            first = await w.wakes.schedule(standing(w))
            plain = await w.remind(repeat=Repeat("daily", 1, datetime.now(UTC).replace(tzinfo=None)))
            later = datetime.now(UTC) + timedelta(days=1)
            assert await w.wakes.settle(first, "turn", later) and await w.wakes.settle(plain, "turn", later)
            assert methods(db_url) == ["research", None, "research", None]
            assert await w.wakes.due(10) == ()   # the next occurrences wait for their time
    run(go())


def test_a_change_keeps_the_method_and_cannot_stop_the_repeat(db_url: str) -> None:
    async def go() -> None:
        async with skilled(db_url) as w:
            made = body(await call(tools_for(w), "remind", {"for": "Alana", "at": tomorrow_at(8), **DAILY,
                                                            "what": "look for new listings", "method": "research"}))
            body(await call(tools_for(w), "change_reminder", {"id": made["id"], "what": "look for new rentals"}))
            once = await call(tools_for(w), "change_reminder", {"id": made["id"], "repeat": "none"})
            assert once.content.startswith("bad_arguments")
            (listed,) = await w.wakes.reminders(w.home, w.alana)
            assert listed.reminder.brief == "look for new rentals" and listed.reminder.method == "research"
            assert listed.reminder.repeat is not None
    run(go())


def test_a_proposed_standing_errand_keeps_its_method() -> None:
    due = datetime(2026, 11, 14, 7, 0, tzinfo=UTC)
    r = Reminder(1, 2, 2, BRIEF, due, Repeat("weekly", 1, datetime(2026, 11, 14, 7, 0)), tools=("switch",),
                 method="research")
    name, stored = encode(ReminderSchedule(r))
    assert name == REMINDERS.name and REMINDERS.decode(stored) == ReminderSchedule(r)
