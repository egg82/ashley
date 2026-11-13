"""An errand's checks in the wakes store, over a real database: `remind` with `errand_hours` stores an errand that ends,
`follow_up` stores one next check per occurrence and moves it on a second call, and refuses past the end, on a
cancelled errand, on a reminder, and once the next check has fired. A proposal keeps the errand's end."""

import json
from datetime import UTC, datetime, timedelta

import pytest
from ashley.senses.proposal_payloads import REMINDERS, ReminderSchedule, encode
from ashley.senses.wakes import Reminder
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import run, scalar
from test_reminder_turn import BRIEF, World, world
from test_reminders_shaped import body, call, tomorrow_at, tools_for


def errand(w: World, hours: float = 2.0, due_in_s: float = -1.0) -> Reminder:
    due = datetime.now(UTC) + timedelta(seconds=due_in_s)
    return Reminder(w.home, w.alana, w.alana, BRIEF, due, None, ends_at=due + timedelta(hours=hours))


def plan_of(url: str, wake_id: int) -> object:
    return scalar(url, f"SELECT plan FROM wakes WHERE id = {wake_id}")


def test_remind_with_errand_hours_stores_an_errand_that_ends_that_many_hours_after_its_first_check(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            made = body(await call(tools_for(w), "remind", {"for": "Alana", "at": tomorrow_at(7),
                                                            "what": "help me get up", "errand_hours": 1.5}))
            (listed,) = await w.wakes.reminders(w.home, w.alana)
            assert listed.id == made["id"] and listed.reminder.plan is None
            assert listed.reminder.ends_at == listed.reminder.due_at + timedelta(hours=1.5)
            shown = body(await call(tools_for(w), "reminders", {}))
            assert "errand_until" in json.dumps(shown)
            repeating = await call(tools_for(w), "remind", {"for": "Alana", "at": tomorrow_at(7), "what": "x",
                                                            "errand_hours": 1, "repeat": "daily"})
            too_long = await call(tools_for(w), "remind", {"for": "Alana", "at": tomorrow_at(7), "what": "x",
                                                           "errand_hours": 1000})
            assert repeating.content.startswith("bad_arguments") and too_long.content.startswith("bad_arguments")
            assert len(await w.wakes.reminders(w.home, w.alana)) == 1
    run(go())


def test_an_errand_that_repeats_falls_due_after_its_end_or_carries_a_plan_is_refused(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            e = errand(w)
            for bad in (Reminder(w.home, w.alana, w.alana, BRIEF, e.due_at + timedelta(hours=3), None,
                                 ends_at=e.ends_at),
                        Reminder(w.home, w.alana, w.alana, BRIEF, e.due_at, None, ends_at=e.ends_at, plan="p")):
                with pytest.raises(ValueError):
                    await w.wakes.schedule(bad)
            assert await w.wakes.reminders(w.home, w.alana) == ()
    run(go())


def test_follow_up_stores_one_next_check_per_occurrence_and_a_second_call_moves_it(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            first = await w.wakes.schedule(errand(w))
            soon = datetime.now(UTC) + timedelta(minutes=10)
            nxt = await w.wakes.follow_up(w.home, first, soon, "tried the lights")
            moved = await w.wakes.follow_up(w.home, first, soon + timedelta(minutes=5), "lights, then music")
            assert nxt is not None and moved == nxt
            assert plan_of(db_url, nxt) == "lights, then music"
            assert scalar(db_url, f"SELECT count(*) FROM wakes WHERE follows = {first}") == 1
            (_, later) = sorted(await w.wakes.reminders(w.home, w.alana), key=lambda s: s.id)
            assert later.reminder.brief == BRIEF and later.reminder.ends_at is not None
            assert abs((later.reminder.due_at - soon).total_seconds() - 300) < 1
    run(go())


def test_follow_up_is_refused_past_the_end_on_another_household_and_on_a_plain_reminder(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            first = await w.wakes.schedule(errand(w, hours=0.25))
            plain = await w.remind()
            late = datetime.now(UTC) + timedelta(minutes=30)
            assert await w.wakes.follow_up(w.home, first, late, "p") is None
            assert await w.wakes.follow_up(w.home + 1, first, late - timedelta(minutes=25), "p") is None
            assert await w.wakes.follow_up(w.home, plain, late - timedelta(minutes=25), "p") is None
            with pytest.raises(ValueError):
                await w.wakes.follow_up(w.home, first, late - timedelta(minutes=25), "")
            assert scalar(db_url, "SELECT count(*) FROM wakes WHERE follows IS NOT NULL") == 0
            assert await w.wakes.follow_up(w.home, first, late - timedelta(minutes=25), "p") is not None
    run(go())


def test_a_cancelled_errand_takes_no_next_check_and_a_fired_next_check_is_never_moved(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            soon = datetime.now(UTC) + timedelta(minutes=10)
            cancelled = await w.wakes.schedule(errand(w))
            assert await w.wakes.cancel(w.home, w.alana, cancelled)
            assert await w.wakes.follow_up(w.home, cancelled, soon, "p") is None
            first = await w.wakes.schedule(errand(w))
            assert await w.wakes.settle(first, "turn")   # its runner settled it before the resumed turn set the next
            nxt = await w.wakes.follow_up(w.home, first, soon, "p")
            assert nxt is not None and await w.wakes.settle(nxt, "turn")
            assert await w.wakes.follow_up(w.home, first, soon, "again") is None
            assert plan_of(db_url, nxt) == "p"
    run(go())


def test_a_proposed_errand_keeps_its_end() -> None:
    due = datetime(2026, 11, 14, 7, 0, tzinfo=UTC)
    r = Reminder(1, 2, 2, BRIEF, due, None, tools=("switch",), ends_at=due + timedelta(hours=1))
    name, stored = encode(ReminderSchedule(r))
    assert name == REMINDERS.name and REMINDERS.decode(stored) == ReminderSchedule(r)
