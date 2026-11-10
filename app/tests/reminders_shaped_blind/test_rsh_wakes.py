"""`Wakes.edit` and a reminder's route on a real database: an edit keeps the row and the occurrences already fired and the
next ones follow it; only the person or its maker may edit, and only while unsettled; an armed money reminder keeps its
time; a quiet reminder is never listed as undelivered, whichever way it was stored."""

import asyncio
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest
from ashley.senses.deposit_rule import DepositRule, Landed
from ashley.senses.repeat import Repeat
from ashley.senses.wakes import Reminder, Scheduled
from contract.conversations_support import run, scalar
from rsh_support import BRIEF, Home, Route, fired_due, home, now

LANDED = Landed(250_000, date(2026, 11, 3), "RSH-Checking", "RSH-Payer")
WEEKLY = Repeat("weekly", 1, datetime(2030, 1, 7, 9, 0), (0, 4))
LISTED = ("sending", "undelivered", "failed")


async def mine(h: Home, who: int | None = None) -> list[Scheduled]:
    return list(await h.wakes.reminders(h.house, h.alana if who is None else who))


def instant(r: Reminder) -> datetime:
    return r.due_at.astimezone(UTC)


def test_an_edit_keeps_the_id_and_replaces_the_brief_time_repeat_route_and_tools(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as h:
            wake = await h.wakes.schedule(h.reminder(due_in_s=3600))
            due = now() + timedelta(days=3)
            changed = replace(h.reminder(brief="a new brief", repeat=WEEKLY), due_at=due, route="quiet", tools=("look_up", "lamp_on"))
            assert await h.wakes.edit(h.house, h.alana, wake, changed) is True
            (got,) = await mine(h)
            assert got.id == wake and got.state == "scheduled"
            r = got.reminder
            assert (r.brief, r.repeat, r.route, r.tools) == ("a new brief", WEEKLY, "quiet", ("look_up", "lamp_on"))
            assert abs(instant(r) - due.astimezone(UTC)) < timedelta(seconds=1)
            assert (r.person_id, r.made_by, r.household_id) == (h.alana, h.alana, h.house)
            assert int(scalar(db_url, "SELECT count(*) FROM wakes")) == 1

    run(go())


def test_an_edit_can_clear_the_repeat_the_tools_and_the_quiet_route(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as h:
            wake = await h.wakes.schedule(h.reminder(repeat=WEEKLY, route="quiet", tools=("look_up",)))
            assert await h.wakes.edit(h.house, h.alana, wake, h.reminder(brief="plain")) is True
            (got,) = await mine(h)
            assert (got.reminder.repeat, got.reminder.route, got.reminder.tools, got.reminder.brief) == (None, "phone", None, "plain")

    run(go())


def test_a_rule_with_weekdays_nth_and_until_is_stored_and_edited_whole(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as h:
            first = Repeat("monthly", 2, datetime(2030, 1, 1, 9, 0), (4,), -1, date(2031, 6, 30))
            wake = await h.wakes.schedule(h.reminder(repeat=first))
            assert (await mine(h))[0].reminder.repeat == first
            second = Repeat("weekly", 2, datetime(2030, 2, 4, 7, 30), (0, 2, 6), None, date(2030, 12, 1))
            assert await h.wakes.edit(h.house, h.alana, wake, h.reminder(repeat=second)) is True
            assert (await mine(h))[0].reminder.repeat == second

    run(go())


def test_an_edit_cannot_change_whom_the_reminder_is_for_or_who_made_it(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as h:
            wake = await h.wakes.schedule(h.reminder(who=h.sam, by=h.alana))
            await h.wakes.edit(h.house, h.alana, wake, h.reminder(who=h.kim, by=h.kim, brief="edited"))
            (got,) = await mine(h, h.alana)
            assert (got.reminder.person_id, got.reminder.made_by, got.reminder.brief) == (h.sam, h.alana, "edited")
            assert await mine(h, h.kim) == []

    run(go())


@pytest.mark.parametrize("editor", ["person", "maker"])
def test_the_person_it_is_for_and_the_person_who_made_it_may_edit(db_url: str, editor: str) -> None:
    async def go() -> None:
        async with home(db_url) as h:
            wake = await h.wakes.schedule(h.reminder(who=h.sam, by=h.alana))
            who = h.sam if editor == "person" else h.alana
            assert await h.wakes.edit(h.house, who, wake, h.reminder(who=h.sam, by=h.alana, brief="theirs")) is True
            assert (await mine(h, h.sam))[0].reminder.brief == "theirs"

    run(go())


def test_someone_else_in_the_household_and_someone_in_another_household_change_nothing(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as h:
            wake = await h.wakes.schedule(h.reminder(who=h.sam, by=h.alana))
            assert await h.wakes.edit(h.house, h.kim, wake, h.reminder(brief="hijack")) is False
            assert await h.wakes.edit(h.house + 1000, h.alana, wake, h.reminder(brief="hijack")) is False
            assert await h.wakes.edit(h.house, h.alana, wake + 1000, h.reminder(brief="hijack")) is False
            assert (await mine(h, h.sam))[0].reminder.brief == BRIEF

    run(go())


@pytest.mark.parametrize("how", ["cancelled", "turn", "failed"])
def test_a_settled_reminder_is_not_edited(db_url: str, how: str) -> None:
    async def go() -> None:
        async with home(db_url) as h:
            wake = await h.wakes.schedule(h.reminder(due_in_s=-5))
            if how == "cancelled":
                assert await h.wakes.cancel(h.house, h.alana, wake) is True
            else:
                assert await h.wakes.settle(wake, "turn" if how == "turn" else "failed") is True
            before = scalar(db_url, "SELECT brief FROM wakes WHERE id = %s", (wake,))
            assert await h.wakes.edit(h.house, h.alana, wake, h.reminder(brief="too late")) is False
            assert scalar(db_url, "SELECT brief FROM wakes WHERE id = %s", (wake,)) == before

    run(go())


@pytest.mark.parametrize("brief", ["", "x" * 501, "a\x00b"])
def test_an_edit_with_a_brief_outside_the_limits_raises_and_changes_nothing(db_url: str, brief: str) -> None:
    async def go() -> None:
        async with home(db_url) as h:
            wake = await h.wakes.schedule(h.reminder())
            with pytest.raises(ValueError):
                await h.wakes.edit(h.house, h.alana, wake, h.reminder(brief=brief, route="quiet"))
            (got,) = await mine(h)
            assert (got.reminder.brief, got.reminder.route) == (BRIEF, "phone")

    run(go())


def test_an_edit_with_too_many_tools_raises_and_changes_nothing(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as h:
            wake = await h.wakes.schedule(h.reminder())
            with pytest.raises(ValueError):
                await h.wakes.edit(h.house, h.alana, wake, h.reminder(tools=tuple(f"t{i}" for i in range(500))))
            assert (await mine(h))[0].reminder.tools is None

    run(go())


def test_an_edit_of_a_repeating_reminder_leaves_the_fired_occurrence_and_the_next_ones_follow_the_edit(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as h:
            first = await h.wakes.schedule(h.reminder(due_in_s=-60, repeat=WEEKLY, brief="old words"))
            future = now() + timedelta(days=2)
            assert await h.wakes.settle(first, "turn", future) is True
            listed = {s.id: s for s in await mine(h)}
            (second,) = [i for i in listed if i != first]
            assert listed[first].state == "sending" and listed[second].state == "scheduled"
            changed = h.reminder(brief="new words", repeat=WEEKLY, route="quiet", tools=("look_up",))
            assert await h.wakes.edit(h.house, h.alana, second, changed) is True
            after = {s.id: s for s in await mine(h)}
            assert after[first].reminder.brief == "old words" and after[first].reminder.route == "phone"
            assert after[first].state == "sending"
            assert (after[second].reminder.brief, after[second].reminder.route, after[second].reminder.tools) == ("new words", "quiet", ("look_up",))
            assert await h.wakes.settle(second, "turn", now() + timedelta(days=4)) is True
            third = [s for s in await mine(h) if s.id not in (first, second) and s.state == "scheduled"]
            assert len(third) == 1
            r = third[0].reminder
            assert (r.brief, r.route, r.tools, r.repeat) == ("new words", "quiet", ("look_up",), WEEKLY)

    run(go())


def test_an_armed_money_reminder_keeps_its_time_and_has_no_repeat_but_may_change_its_words_route_and_tools(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as h:
            rule = DepositRule("acct-1", "RSH-Checking", 100_000, "Acme", "contains")
            armed_at = now() - timedelta(hours=5)
            wake = await h.deposits.arm(replace(h.reminder(brief="when it lands"), due_at=armed_at), rule)
            changed = replace(h.reminder(brief="say it plainly", repeat=WEEKLY, route="quiet", tools=("look_up",)), due_at=now() + timedelta(days=9))
            assert await h.wakes.edit(h.house, h.alana, wake, changed) is True
            (got,) = [s for s in await mine(h) if s.id == wake]
            r = got.reminder
            assert (r.brief, r.route, r.tools) == ("say it plainly", "quiet", ("look_up",))
            assert r.repeat is None
            assert abs(instant(r) - armed_at.astimezone(UTC)) < timedelta(seconds=1)
            assert got.deposit == rule

    run(go())


async def _due_reminder(h: Home, route: Route, landed: Landed | None) -> int:
    """A due reminder of `route`, scheduled by time or, with `landed`, armed and fired by a deposit."""
    if landed is None:
        return await h.wakes.schedule(h.reminder(due_in_s=-5, route=route))
    armed = await h.deposits.arm(h.reminder(route=route), RULE)
    assert await h.deposits.fire(armed, f"tx-{route}", landed) is True
    (fired,) = [wake_id for wake_id, r in await fired_due(h) if r.route == route]
    return fired


@pytest.mark.parametrize("landed", [None, LANDED], ids=["no_deposit", "landed"])
def test_a_quiet_reminder_that_fired_is_never_listed_nor_handed_out_for_a_push_but_a_phone_one_is(db_url: str, landed: Landed | None) -> None:
    async def go() -> None:
        async with home(db_url) as h:
            quiet = await _due_reminder(h, "quiet", landed)
            phone = await _due_reminder(h, "phone", landed)
            assert await h.wakes.settle(quiet, "turn") is True and await h.wakes.settle(phone, "turn") is True
            assert {s.id: s.state for s in await mine(h) if s.deposit is None} == {phone: "sending"}
            handed = {d.id for d in await h.wakes.undelivered(50, 0.0, 10_000.0)}
            assert handed == {phone}
            assert await h.wakes.claim(quiet, 0.0) is False
            assert await h.wakes.claim(phone, 0.0) is True

    run(go())


RULE = DepositRule("acct-1", "RSH-Checking", 100_000, "Acme", "contains")


def test_a_reminder_a_deposit_fired_from_an_armed_one_edited_quiet_is_quiet_and_names_its_tools(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as h:
            armed = await h.deposits.arm(h.reminder(brief="move it"), RULE)
            assert await h.wakes.edit(h.house, h.alana, armed, h.reminder(brief="move it", route="quiet", tools=("look_up",))) is True
            assert await h.deposits.fire(armed, "tx-1", LANDED) is True
            ((wake_id, fired),) = await fired_due(h)
            assert (fired.route, fired.tools) == ("quiet", ("look_up",))
            assert await h.wakes.settle(wake_id, "turn") is True
            assert [s for s in await mine(h) if s.deposit is None] == []
            assert await h.wakes.undelivered(50, 0.0, 10_000.0) == ()

    run(go())


def test_a_reminder_armed_with_a_route_and_tools_keeps_them(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as h:
            armed = await h.deposits.arm(h.reminder(brief="move it", route="quiet", tools=("look_up",)), RULE)
            (got,) = [s for s in await mine(h) if s.id == armed]
            assert (got.reminder.route, got.reminder.tools) == ("quiet", ("look_up",))
            assert await h.deposits.fire(armed, "tx-1", LANDED) is True
            ((_, fired),) = await fired_due(h)
            assert (fired.route, fired.tools) == ("quiet", ("look_up",))

    run(go())


def test_a_reminder_a_deposit_fired_from_a_phone_one_is_handed_out_for_a_push(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as h:
            armed = await h.deposits.arm(h.reminder(brief="move it"), RULE)
            assert await h.deposits.fire(armed, "tx-1", LANDED) is True
            ((wake_id, fired),) = await fired_due(h)
            assert fired.route == "phone" and fired.landed == LANDED
            assert await h.wakes.settle(wake_id, "turn") is True
            assert [d.id for d in await h.wakes.undelivered(50, 0.0, 10_000.0)] == [wake_id]

    run(go())


def test_a_reminder_scheduled_with_a_deposit_is_refused_and_stores_nothing(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as h:
            with pytest.raises(ValueError):
                await h.wakes.schedule(h.reminder(due_in_s=-5, landed=LANDED))
            assert await fired_due(h) == []
            assert await mine(h) == []

    run(go())


def test_a_quiet_reminder_that_is_still_to_fire_is_listed_with_its_route(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as h:
            await h.wakes.schedule(h.reminder(route="quiet"))
            (got,) = await mine(h)
            assert (got.state, got.reminder.route) == ("scheduled", "quiet")

    run(go())


def test_two_edits_at_once_leave_one_whole_reminder(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as h:
            wake = await h.wakes.schedule(h.reminder())
            a = h.reminder(brief="AAAA", route="quiet", tools=("look_up",))
            b = h.reminder(brief="BBBB", route="phone", tools=("lamp_on",))
            assert await asyncio.gather(h.wakes.edit(h.house, h.alana, wake, a), h.wakes.edit(h.house, h.alana, wake, b)) == [True, True]
            r = (await mine(h))[0].reminder
            assert (r.brief, r.route, r.tools) in {("AAAA", "quiet", ("look_up",)), ("BBBB", "phone", ("lamp_on",))}

    run(go())
