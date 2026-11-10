"""Her reminder tools over a real database: `remind` sets a reminder for a person of the household, by name from a
list the catalogue offers, at a wall-clock time in the household's zone, once or repeating by a structured rule;
`reminders` and `cancel_reminder` are offered only where the reply reaches the speaker alone; a turn whose channel
does not name the speaker is offered none; bad arguments store nothing; and no log line carries an argument."""

import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from ashley import logs, services
from ashley.channels import turn_tools
from ashley.channels.model import Inbound
from ashley.db.pool import PoolDatabase
from ashley.inference.model import ToolCall
from ashley.people.model import Household, Person
from ashley.people.people import People
from ashley.senses.postgres_wakes import PostgresWakes
from ashley.senses.repeat import Repeat
from ashley.senses.wakes import Wakes
from ashley.tools.reminders import ReminderTools
from ashley.tools.tools import Tools
from contract.conversations_support import db_url as db_url, household, migrated_template as migrated_template
from contract.conversations_support import person, run
from test_reminder_turn import Home
from wake_support import Switchboard

DENVER = ZoneInfo("America/Denver")
WHAT = "Move anything over $300 in Bluebird checking to savings."


@dataclass
class World:
    home: int
    alana: int
    sam: int
    wakes: Wakes


@asynccontextmanager
async def world(url: str) -> AsyncGenerator[World]:
    db = PoolDatabase(url, connect_timeout_s=5.0)
    await db.open()
    home = household(url)
    alana, sam = person(url, home, "Alana"), person(url, home, "Sam")
    w = World(home, alana, sam, PostgresWakes(db))
    services.register(People, Home(Household(home, "home", "America/Denver", "",
                                             (Person(alana, home, "Alana"), Person(sam, home, "Sam")))))
    services.register(Wakes, w.wakes)
    try:
        yield w
    finally:
        services.unregister(People)
        services.unregister(Wakes)
        await db.close()


def soon(days: int = 3) -> str:
    return (datetime.now(DENVER) + timedelta(days=days)).strftime("%Y-%m-%dT09:00")


def body(result: str) -> dict[str, object]:
    return json.loads(result)


def test_remind_sets_one_for_another_person_at_local_time_and_they_both_see_it(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            tools = ReminderTools(w.home, w.alana, private=True)
            [spec, *_] = (await tools.catalogue()).specs
            assert spec.name == "remind" and not spec.reads
            assert json.dumps(spec.parameters).count('"Sam"') == 1
            at = soon()
            got = await tools.call(ToolCall("c1", "remind", {"for": "Sam", "at": at, "what": WHAT}))
            assert not got.is_error, got.content
            [mine] = await w.wakes.reminders(w.home, w.alana)
            [theirs] = await w.wakes.reminders(w.home, w.sam)
            assert mine == theirs and body(got.content)["id"] == mine.id
            r = mine.reminder
            assert (r.person_id, r.made_by, r.brief, r.repeat) == (w.sam, w.alana, WHAT, None)
            assert r.due_at.astimezone(DENVER).strftime("%Y-%m-%dT%H:%M") == at
    run(go())


def test_remind_repeating_monthly_stores_the_rule_anchored_at_the_first_time(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            tools = ReminderTools(w.home, w.alana, private=False)
            at = soon(10)
            got = await tools.call(ToolCall("c1", "remind", {"for": "Alana", "at": at, "repeat": "monthly",
                                                             "what": WHAT}))
            assert not got.is_error, got.content
            [s] = await w.wakes.reminders(w.home, w.alana)
            assert s.reminder.repeat == Repeat("monthly", 1, datetime.fromisoformat(at))
    run(go())


@pytest.mark.parametrize("args", [
    {"for": "Kim", "at": "2030-01-01T09:00", "what": WHAT},
    {"for": "Alana", "at": "2020-01-01T09:00", "what": WHAT},
    {"for": "Alana", "at": "next friday", "what": WHAT},
    {"for": "Alana", "at": "2030-01-01T09:00-07:00", "what": WHAT},
    {"for": "Alana", "at": "2030-01-01T9:00", "what": WHAT},
    {"for": "Alana", "at": "2030-1-1T09:00", "what": WHAT},
    {"for": "Alana", "at": "2030-01-01T09:00", "repeat": "hourly", "what": WHAT},
    {"for": "Alana", "at": "2030-01-01T09:00", "repeat": "daily", "every": 0, "what": WHAT},
    {"for": "Alana", "at": "2030-01-01T09:00", "what": ""},
    {"for": "Alana", "at": "2030-01-01T09:00", "what": "x" * 501},
    {"for": "Alana", "at": "2030-01-01T09:00", "what": WHAT, "note": "extra"},
])
def test_remind_with_a_bad_argument_is_an_error_and_stores_nothing(db_url: str, args: dict[str, object]) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            got = await ReminderTools(w.home, w.alana, private=True).call(ToolCall("c1", "remind", args))
            assert got.is_error and await w.wakes.reminders(w.home, w.alana) == ()
    run(go())


def test_listing_and_cancelling_are_offered_only_where_the_speaker_alone_reads_the_reply(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            shared = [s.name for s in (await ReminderTools(w.home, w.alana, private=False).catalogue()).specs]
            alone = [s.name for s in (await ReminderTools(w.home, w.alana, private=True).catalogue()).specs]
            assert shared == ["remind"] and alone == ["remind", "reminders", "cancel_reminder", "change_reminder"]
            got = await ReminderTools(w.home, w.alana, private=False).call(ToolCall("c1", "reminders", {}))
            assert got.is_error
    run(go())


def test_she_lists_and_cancels_the_speakers_reminders(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            tools = ReminderTools(w.home, w.alana, private=True)
            made = body((await tools.call(ToolCall("c1", "remind", {"for": "Alana", "at": soon(), "repeat": "weekly",
                                                                    "every": 2, "what": WHAT}))).content)["id"]
            listed = body((await tools.call(ToolCall("c2", "reminders", {}))).content)
            assert listed == {"reminders": [{"id": made, "for": "Alana", "made_by": "Alana", "at": soon(),
                                             "repeat": "weekly", "every": 2, "what": WHAT, "state": "scheduled"}]}
            sams = ReminderTools(w.home, w.sam, private=True)
            assert (await sams.call(ToolCall("c3", "cancel_reminder", {"id": made}))).is_error
            assert not (await tools.call(ToolCall("c4", "cancel_reminder", {"id": made}))).is_error
            assert await w.wakes.reminders(w.home, w.alana) == ()
    run(go())


BASE = Inbound(household_id=1, thread="web:1", text="hi", kind="chat", medium="text", audience="owner", speaker_id=1,
               shared=False, place=None, channel="web")


def inbound(**fields: object) -> Inbound:
    return replace(BASE, **fields)


def test_a_turn_is_offered_reminders_only_when_its_channel_names_the_speaker() -> None:
    services.register(Tools, Switchboard())
    try:
        assert "reminders" in turn_tools.sources(inbound())
        assert "reminders" in turn_tools.sources(inbound(audience="present", shared=True, place="kitchen"))
        assert "reminders" not in turn_tools.sources(inbound(speaker_id=None))
    finally:
        services.unregister(Tools)


def test_no_log_line_carries_an_argument(db_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()

    async def go() -> None:
        async with world(db_url) as w:
            tools = ReminderTools(w.home, w.alana, private=True)
            await tools.call(ToolCall("c1", "remind", {"for": "Sam", "at": soon(), "what": WHAT}))
            await tools.call(ToolCall("c2", "reminders", {}))
    run(go())
    out = capsys.readouterr().out
    assert "event=tools.call" in out
    for value in ("Bluebird", "$300", "Sam", "T09:00"):
        assert value not in out, value


def test_a_date_with_no_time_is_nine_in_the_morning_household_time_and_the_spec_says_so(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            tools = ReminderTools(w.home, w.alana, private=True)
            [spec, *_] = (await tools.catalogue()).specs
            assert "09:00" in json.dumps(spec.parameters)
            day = soon(4)[:10]
            got = await tools.call(ToolCall("c1", "remind", {"for": "Alana", "at": day, "repeat": "monthly",
                                                             "what": WHAT}))
            assert not got.is_error, got.content
            [s] = await w.wakes.reminders(w.home, w.alana)
            assert s.reminder.due_at.astimezone(DENVER).strftime("%Y-%m-%dT%H:%M") == f"{day}T09:00"
            assert s.reminder.repeat == Repeat("monthly", 1, datetime.fromisoformat(f"{day}T09:00"))
    run(go())
