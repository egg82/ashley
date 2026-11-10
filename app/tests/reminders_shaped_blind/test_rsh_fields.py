"""`change_reminder` and the fields `remind` takes (weekdays, nth, count, until, delivery, the first time): an edit keeps the
id and what it was not given, the first time is the household's wall clock, and fields that make no rule set nothing."""

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from ashley.senses.repeat import Repeat, next_after, until_after
from contract.conversations_support import run
from rsh_support import ACT, BRIEF, DENVER, PHOENIX, READ, TOMORROW, Home, Shelf, body, home, now, offered, proposed, remind_args, stored, use


async def seed(h: Home, **args: object) -> int:
    result = await use(h.tools(turn=(9, 1)), "remind", remind_args(**args))
    assert result.is_error is False
    wake = body(result)["id"]
    assert isinstance(wake, int)
    return wake


def test_an_edit_that_adds_no_acting_tool_takes_effect_at_once_and_keeps_the_id_and_the_rest(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as h:
            wake = await seed(h, repeat="weekly", weekdays=["mon", "fri"], until=(TOMORROW + timedelta(days=90)).isoformat())
            shelf = Shelf(READ, ACT)
            result = await use(h.tools(turn=(1, 10), shelf=shelf), "change_reminder", {"id": wake, "what": "new words", "delivery": "quiet", "tools": ["look_up"]})
            assert result.is_error is False
            (got,) = await stored(h)
            r = got.reminder
            assert got.id == wake and (r.brief, r.route, r.tools) == ("new words", "quiet", ("look_up",))
            assert r.repeat is not None and r.repeat.weekdays == (0, 4) and r.repeat.until == TOMORROW + timedelta(days=90)
            assert "arm_reminder" not in await offered(h.tools(turn=(1, 11), shelf=shelf))

    run(go())


def test_an_edit_that_adds_an_acting_tool_changes_nothing_until_armed_and_then_keeps_the_id(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as h:
            wake = await seed(h, what="old words")
            shelf = Shelf(READ, ACT)
            result = await use(h.tools(turn=(1, 10), shelf=shelf), "change_reminder", {"id": wake, "what": "new words", "tools": ["lamp_on"]})
            assert result.is_error is False and body(result).get("armed") is False
            (before,) = await stored(h)
            assert (before.reminder.brief, before.reminder.tools) == ("old words", None)
            assert (await use(h.tools(turn=(1, 10), shelf=shelf), "arm_reminder")).is_error is True
            assert (await use(h.tools(turn=(1, 11), shelf=shelf), "arm_reminder")).is_error is False
            (after,) = await stored(h)
            assert after.id == wake and (after.reminder.brief, after.reminder.tools) == ("new words", ("lamp_on",))

    run(go())


def test_a_proposed_edit_is_replaced_by_a_newer_proposal_of_any_kind(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as h:
            wake = await seed(h, what="old words")
            shelf = Shelf(READ, ACT)
            await use(h.tools(turn=(1, 10), shelf=shelf), "change_reminder", {"id": wake, "what": "EDIT", "tools": ["lamp_on"]})
            await proposed(h, shelf, 10, tools=["lamp_on"], what="NEW ONE")
            assert (await use(h.tools(turn=(1, 11), shelf=shelf), "arm_reminder")).is_error is False
            assert sorted(s.reminder.brief for s in await stored(h)) == ["NEW ONE", "old words"]

    run(go())


def test_a_change_to_a_reminder_that_is_not_theirs_is_refused(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as h:
            wake = await seed(h, **{"for": "Alana"})
            result = await use(h.tools(speaker=h.kim, turn=(1, 10)), "change_reminder", {"id": wake, "what": "mine now"})
            assert result.is_error is True
            assert (await stored(h))[0].reminder.brief == BRIEF
            gone = await use(h.tools(turn=(1, 10)), "change_reminder", {"id": wake + 99, "what": "x"})
            assert gone.is_error is True

    run(go())


def test_changing_the_time_moves_the_next_one_and_starts_a_monthly_rule_over_from_there(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as h:
            wake = await seed(h, at="2099-01-31T09:00", repeat="monthly")
            result = await use(h.tools(turn=(1, 10)), "change_reminder", {"id": wake, "at": "2099-04-30T09:00"})
            assert result.is_error is False
            (got,) = await stored(h)
            r = got.reminder
            assert r.due_at.astimezone(DENVER).strftime("%Y-%m-%dT%H:%M") == "2099-04-30T09:00"
            assert r.repeat is not None
            nxt = next_after(r.repeat, r.due_at, DENVER)
            assert nxt is not None and nxt.astimezone(DENVER).strftime("%Y-%m-%d %H:%M") == "2099-05-30 09:00"
            assert r.brief == BRIEF

    run(go())


@pytest.mark.parametrize("change,field,expected", [
    ({"every": 3}, "every", 3), ({"every": 3}, "weekdays", (0, 2)),
    ({"weekdays": ["tue", "thu"]}, "weekdays", (1, 3)), ({"weekdays": ["tue", "thu"]}, "every", 2),
    ({"until": "2099-09-01"}, "until", date(2099, 9, 1)), ({"until": "2099-09-01"}, "every", 2)])
def test_changing_the_rule_alone_changes_it_and_keeps_the_rest(db_url: str, change: dict[str, object], field: str, expected: object) -> None:
    async def go() -> None:
        async with home(db_url) as h:
            wake = await seed(h, at="2099-01-05T09:00", repeat="weekly", weekdays=["mon", "wed"], every=2)
            assert (await use(h.tools(turn=(1, 10)), "change_reminder", {"id": wake, **change})).is_error is False
            (got,) = await stored(h)
            r = got.reminder.repeat
            assert r is not None and r.freq == "weekly" and got.reminder.brief == BRIEF
            assert getattr(r, field) == expected

    run(go())


def test_an_edit_that_names_no_new_acting_tool_is_at_once_and_keeps_the_route_and_tools_it_was_not_given(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as h:
            shelf = Shelf(READ, ACT)
            await proposed(h, shelf, 10, tools=["lamp_on", "look_up"], delivery="quiet", what="old words")
            assert (await use(h.tools(turn=(1, 11), shelf=shelf), "arm_reminder")).is_error is False
            (armed,) = await stored(h)
            result = await use(h.tools(turn=(1, 12), shelf=shelf), "change_reminder", {"id": armed.id, "what": "new words"})
            assert result.is_error is False and body(result).get("armed") is None
            (got,) = await stored(h)
            r = got.reminder
            assert (r.brief, r.route, set(r.tools or ())) == ("new words", "quiet", {"lamp_on", "look_up"})
            assert "arm_reminder" not in await offered(h.tools(turn=(1, 13), shelf=shelf))

    run(go())


def test_changing_only_the_words_leaves_the_time_and_rule(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as h:
            wake = await seed(h, repeat="weekly", weekdays=["wed"], every=2)
            (before,) = await stored(h)
            assert (await use(h.tools(turn=(1, 10)), "change_reminder", {"id": wake, "what": "other"})).is_error is False
            (after,) = await stored(h)
            assert after.reminder.repeat == before.reminder.repeat and after.reminder.due_at == before.reminder.due_at
            assert after.reminder.brief == "other"

    run(go())


def test_a_weekly_reminder_with_weekdays_and_a_count_is_stored_with_the_day_of_its_last_time_only(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as h:
            result = await use(h.tools(turn=(1, 10)), "remind", remind_args(at="2099-01-07T18:00", repeat="weekly", weekdays=["sun"], count=6))
            assert result.is_error is False
            (got,) = await stored(h)
            r = got.reminder.repeat
            assert r is not None and r.weekdays == (6,) and r.until == until_after(Repeat("weekly", 1, datetime(2099, 1, 7, 18, 0), (6,)), 6)
            assert got.reminder.due_at.astimezone(DENVER).strftime("%Y-%m-%d %H:%M") == "2099-01-11 18:00"

    run(go())


def test_an_edit_does_not_restart_a_count(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as h:
            wake = await seed(h, at="2099-01-07T18:00", repeat="weekly", weekdays=["sun"], count=6)
            (before,) = await stored(h)
            assert (await use(h.tools(turn=(1, 10)), "change_reminder", {"id": wake, "what": "words"})).is_error is False
            (after,) = await stored(h)
            assert before.reminder.repeat is not None and after.reminder.repeat is not None
            assert after.reminder.repeat.until == before.reminder.repeat.until

    run(go())


def test_the_nth_weekday_of_the_month_is_set_from_fields(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as h:
            result = await use(h.tools(turn=(1, 10)), "remind", remind_args(at="2099-01-01T09:00", repeat="monthly", weekdays=["mon"], nth=1))
            assert result.is_error is False
            (got,) = await stored(h)
            assert got.reminder.due_at.astimezone(DENVER).strftime("%Y-%m-%d") == "2099-01-05"
            assert got.reminder.repeat == Repeat("monthly", 1, datetime(2099, 1, 1, 9, 0), (0,), 1)

    run(go())


@pytest.mark.parametrize("extra", [
    {"repeat": "daily", "weekdays": ["mon"]}, {"repeat": "yearly", "weekdays": ["mon"]},
    {"repeat": "weekly", "until": "2000-01-01"}, {"repeat": "weekly", "until": "2099-06-01", "count": 3},
    {"repeat": "monthly", "weekdays": ["mon"], "nth": 5}, {"repeat": "weekly", "weekdays": ["someday"]},
    {"delivery": "carrier-pigeon"}])
def test_fields_that_make_no_rule_set_nothing(db_url: str, extra: dict[str, object]) -> None:
    async def go() -> None:
        async with home(db_url) as h:
            result = await use(h.tools(turn=(1, 10)), "remind", remind_args(at="2099-01-07T09:00", **extra))
            assert result.is_error is True
            assert await stored(h) == []

    run(go())


def test_a_past_time_is_refused_for_a_one_off_and_rolls_forward_for_a_repeating_one(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as h:
            assert (await use(h.tools(turn=(1, 10)), "remind", remind_args(at="2020-01-01T09:00"))).is_error is True
            assert await stored(h) == []
            rolled = await use(h.tools(turn=(1, 10)), "remind", remind_args(at="2020-01-01T09:00", repeat="weekly", weekdays=["mon"]))
            assert rolled.is_error is False
            (got,) = await stored(h)
            local = got.reminder.due_at.astimezone(DENVER)
            assert local.weekday() == 0 and (local.hour, local.minute) == (9, 0)
            assert now() < got.reminder.due_at <= now() + timedelta(days=7, hours=1)

    run(go())


def test_a_date_alone_is_nine_in_the_morning_in_the_households_zone_and_phoenix_does_not_shift(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url, PHOENIX) as h:
            result = await use(h.tools(turn=(1, 10)), "remind", remind_args(at="2099-07-01", repeat="weekly", weekdays=["wed"]))
            assert result.is_error is False
            (got,) = await stored(h)
            assert got.reminder.due_at.astimezone(PHOENIX).strftime("%Y-%m-%d %H:%M") == "2099-07-01 09:00"
            assert got.reminder.due_at.astimezone(UTC).hour == 16

    run(go())


def test_the_quiet_route_is_stored_and_phone_is_the_default(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as h:
            await use(h.tools(turn=(1, 10)), "remind", remind_args(delivery="quiet"))
            await use(h.tools(turn=(1, 10)), "remind", remind_args(what="loud"))
            routes = {s.reminder.brief: s.reminder.route for s in await stored(h)}
            assert routes == {BRIEF: "quiet", "loud": "phone"}

    run(go())


def test_a_listed_reminder_shows_its_weekdays_until_and_route(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as h:
            await use(h.tools(turn=(1, 10)), "remind", remind_args(at="2099-01-07T09:00", repeat="weekly", weekdays=["fri", "mon"], until="2099-03-01", delivery="quiet"))
            listed: list[dict[str, Any]] = body(await use(h.tools(turn=(1, 10)), "reminders"))["reminders"]
            assert len(listed) == 1
            row = listed[0]
            assert row["weekdays"] == ["mon", "fri"] and row["until"] == "2099-03-01" and row["repeat"] == "weekly"

    run(go())
