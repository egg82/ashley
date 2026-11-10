"""`ashley.tools.reminder_shape`: the fields she sets turned into a rule, a first time, a route and a tool list, or refused
with `BadArguments`; the household's wall clock throughout."""

from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest
from ashley.inference.model import ToolSpec
from ashley.senses.repeat import MAX_COUNT, Repeat, instant, until_after
from ashley.tools.bench_args import BadArguments
from ashley.tools.reminder_shape import acts, first_due, repeat_of, route_of, tools_of

ZONE = ZoneInfo("America/Denver")
NOW = datetime(2026, 11, 4, 18, 0, tzinfo=UTC)
ANCHOR = datetime(2026, 11, 9, 8, 30)
USABLE: Mapping[str, ToolSpec] = {
    "look_up": ToolSpec("look_up", "look", {"type": "object"}, reads=True),
    "lamp_on": ToolSpec("lamp_on", "act", {"type": "object"}, reads=False),
}
BASE = Repeat("weekly", 2, datetime(2026, 1, 5, 7, 0), (0, 2), None, date(2027, 1, 1))


def aware(x: datetime) -> datetime:
    return x if x.tzinfo else instant(x, ZONE)


def test_a_route_left_out_is_the_default_and_one_given_is_that_one() -> None:
    assert route_of(None, "phone") == "phone" and route_of(None, "quiet") == "quiet"
    assert route_of("quiet", "phone") == "quiet" and route_of("phone", "quiet") == "phone"


@pytest.mark.parametrize("raw", ["push", "QUIET", 3, ["quiet"], ""])
def test_a_route_that_is_neither_phone_nor_quiet_is_refused(raw: object) -> None:
    with pytest.raises(BadArguments):
        route_of(raw, "phone")


def test_no_tools_given_is_none_and_those_the_person_can_use_come_back_by_name() -> None:
    assert tools_of(None, USABLE) is None
    assert tools_of(["look_up"], USABLE) == ("look_up",)
    assert set(tools_of(["lamp_on", "look_up"], USABLE) or ()) == {"lamp_on", "look_up"}


@pytest.mark.parametrize("raw", [["hacking"], ["look_up", "money_move"], ["remind"], "look_up", [3]])
def test_a_tool_the_person_cannot_use_now_is_refused(raw: object) -> None:
    with pytest.raises(BadArguments):
        tools_of(raw, USABLE)


def test_a_tool_cannot_be_named_when_there_are_none_to_use() -> None:
    with pytest.raises(BadArguments):
        tools_of(["look_up"], {})


def test_a_list_of_tools_acts_when_any_changes_something() -> None:
    assert acts(("look_up",), USABLE) is False
    assert acts(("lamp_on",), USABLE) is True
    assert acts(("look_up", "lamp_on"), USABLE) is True
    assert acts(None, USABLE) is False


def test_a_one_off_time_ahead_is_that_time() -> None:
    local = datetime(2026, 11, 5, 9, 0)
    assert aware(first_due(None, local, ZONE, NOW)) == instant(local, ZONE)


def test_a_one_off_time_that_is_exactly_now_is_not_ahead() -> None:
    with pytest.raises(BadArguments):
        first_due(None, datetime(2026, 11, 4, 11, 0), ZONE, NOW)
    assert aware(first_due(None, datetime(2026, 11, 4, 11, 1), ZONE, NOW)) == instant(datetime(2026, 11, 4, 11, 1), ZONE)


def test_a_rule_whose_first_time_is_exactly_now_is_due_at_the_next_one() -> None:
    rule = Repeat("daily", 1, datetime(2026, 11, 4, 11, 0))
    assert aware(first_due(rule, datetime(2026, 11, 4, 11, 0), ZONE, NOW)) == instant(datetime(2026, 11, 5, 11, 0), ZONE)


def test_a_one_off_time_that_has_passed_is_refused() -> None:
    with pytest.raises(BadArguments):
        first_due(None, datetime(2026, 11, 4, 10, 0), ZONE, NOW)


def test_a_rule_whose_first_time_is_ahead_is_due_at_its_first_occurrence() -> None:
    rule = Repeat("weekly", 1, datetime(2026, 11, 7, 9, 0), (0, 4))
    assert aware(first_due(rule, datetime(2026, 11, 7, 9, 0), ZONE, NOW)) == instant(datetime(2026, 11, 9, 9, 0), ZONE)


def test_a_rule_whose_first_time_has_passed_is_due_at_the_next_one_after_now() -> None:
    rule = Repeat("weekly", 1, datetime(2026, 1, 1, 9, 0), (0, 4))
    got = aware(first_due(rule, datetime(2026, 1, 1, 9, 0), ZONE, NOW))
    assert got == instant(datetime(2026, 11, 6, 9, 0), ZONE)
    nth = Repeat("monthly", 1, datetime(2020, 1, 1, 9, 0), (4,), -1)
    assert aware(first_due(nth, datetime(2020, 1, 1, 9, 0), ZONE, NOW)) == instant(datetime(2026, 11, 27, 9, 0), ZONE)


def test_none_of_the_repeat_keys_moves_the_base_to_the_anchor() -> None:
    got = repeat_of({"what": "x"}, ANCHOR, BASE)
    assert got == replace(BASE, anchor=ANCHOR)


def test_a_new_repeat_is_made_from_the_arguments_alone_and_forgets_the_base() -> None:
    got = repeat_of({"repeat": "monthly", "weekdays": ["fri"], "nth": -1}, ANCHOR, BASE)
    assert got == Repeat("monthly", 1, ANCHOR, (4,), -1)
    assert repeat_of({"repeat": "daily", "every": 3}, ANCHOR, BASE) == Repeat("daily", 3, ANCHOR)


def test_repeat_none_is_once() -> None:
    assert repeat_of({"repeat": "none"}, ANCHOR, BASE) is None
    assert repeat_of({}, ANCHOR, None) is None


def test_other_keys_alone_change_the_base() -> None:
    assert repeat_of({"every": 3}, ANCHOR, BASE) == replace(BASE, every=3, anchor=ANCHOR)
    assert repeat_of({"weekdays": ["tue", "sun"]}, ANCHOR, BASE) == replace(BASE, weekdays=(1, 6), anchor=ANCHOR)
    assert repeat_of({"until": "2026-12-31"}, ANCHOR, BASE) == replace(BASE, until=date(2026, 12, 31), anchor=ANCHOR)


def test_weekday_names_become_ascending_numbers_whatever_their_order() -> None:
    got = repeat_of({"repeat": "weekly", "weekdays": ["sun", "mon", "fri"]}, ANCHOR, None)
    assert got is not None and got.weekdays == (0, 4, 6)


def test_a_count_becomes_the_day_of_that_occurrence_and_is_not_stored() -> None:
    got = repeat_of({"repeat": "weekly", "weekdays": ["sun"], "count": 6}, datetime(2026, 11, 2, 18, 0), None)
    assert got == Repeat("weekly", 1, datetime(2026, 11, 2, 18, 0), (6,), None, date(2026, 12, 13))
    plain = Repeat("weekly", 1, datetime(2026, 11, 2, 18, 0), (6,))
    assert got is not None and got.until == until_after(plain, 6)


@pytest.mark.parametrize("args", [
    {"repeat": "daily", "weekdays": ["mon"]}, {"repeat": "yearly", "weekdays": ["mon"]},
    {"repeat": "weekly", "weekdays": ["funday"]}, {"repeat": "monthly", "weekdays": ["mon"], "nth": 5},
    {"repeat": "weekly", "until": "2026-11-01"}, {"repeat": "weekly", "until": "2026-12-31", "count": 3},
    {"repeat": "weekly", "count": 0}, {"repeat": "weekly", "count": MAX_COUNT + 1}, {"repeat": "fortnightly"},
    {"repeat": "weekly", "every": 0}])
def test_arguments_that_make_no_rule_are_refused(args: dict[str, object]) -> None:
    with pytest.raises(BadArguments):
        repeat_of(args, ANCHOR, None)
