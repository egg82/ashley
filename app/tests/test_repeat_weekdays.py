"""A repeat on weekdays and with an end: every weekday, the first Monday of the month, the last Friday, every other
Tuesday and Thursday, `until` a day, or for a count of times; each occurrence the household's wall time across daylight
saving; the rule stored as it was before these fields existed when it uses none."""

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest
from ashley.senses.repeat import MAX_COUNT, Repeat, freq_of, from_json, instant, next_after, starts, to_json, until_after
from repeat_support import next_of

DENVER = ZoneInfo("America/Denver")
MON, TUE, WED, THU, FRI, SAT, SUN = range(7)


def utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


def local_days(repeat: Repeat, after: datetime, n: int) -> list[str]:
    """The next `n` occurrences after `after`, as local `weekday date`."""
    out: list[str] = []
    while len(out) < n:
        got = next_after(repeat, after, DENVER)
        assert got is not None
        out.append(got.astimezone(DENVER).strftime("%a %Y-%m-%d %H:%M"))
        after = got
    return out


def test_every_weekday_skips_the_weekend_and_starts_on_the_first_weekday_on_or_after_the_anchor() -> None:
    weekdays = Repeat("weekly", 1, datetime(2026, 11, 7, 8, 0), (MON, TUE, WED, THU, FRI))
    assert starts(weekdays) == datetime(2026, 11, 9, 8, 0)
    assert local_days(weekdays, utc(2026, 11, 6), 7) == [
        "Mon 2026-11-09 08:00", "Tue 2026-11-10 08:00", "Wed 2026-11-11 08:00", "Thu 2026-11-12 08:00",
        "Fri 2026-11-13 08:00", "Mon 2026-11-16 08:00", "Tue 2026-11-17 08:00"]


def test_every_other_week_on_two_days_keeps_the_gap() -> None:
    biweekly = Repeat("weekly", 2, datetime(2026, 11, 3, 18, 30), (TUE, THU))
    assert local_days(biweekly, utc(2026, 11, 1), 5) == [
        "Tue 2026-11-03 18:30", "Thu 2026-11-05 18:30", "Tue 2026-11-17 18:30", "Thu 2026-11-19 18:30",
        "Tue 2026-12-01 18:30"]


def test_the_first_monday_and_the_last_friday_of_each_month() -> None:
    first_monday = Repeat("monthly", 1, datetime(2026, 11, 1, 9, 0), (MON,), 1)
    assert local_days(first_monday, utc(2026, 10, 1), 4) == [
        "Mon 2026-11-02 09:00", "Mon 2026-12-07 09:00", "Mon 2027-01-04 09:00", "Mon 2027-02-01 09:00"]
    last_friday = Repeat("monthly", 1, datetime(2026, 11, 1, 9, 0), (FRI,), -1)
    assert local_days(last_friday, utc(2026, 10, 1), 3) == [
        "Fri 2026-11-27 09:00", "Fri 2026-12-25 09:00", "Fri 2027-01-29 09:00"]


def test_a_month_whose_nth_weekday_is_before_the_anchor_waits_for_the_next_month() -> None:
    second_tuesday = Repeat("monthly", 1, datetime(2026, 11, 20, 9, 0), (TUE,), 2)
    assert starts(second_tuesday) == datetime(2026, 12, 8, 9, 0)


def test_an_end_date_is_the_last_day_it_may_fall_on_and_the_rule_then_has_no_next() -> None:
    until = Repeat("weekly", 1, datetime(2026, 11, 1, 9, 0), (SUN,), None, date(2026, 11, 15))
    assert local_days(until, utc(2026, 10, 1), 3) == ["Sun 2026-11-01 09:00", "Sun 2026-11-08 09:00",
                                                      "Sun 2026-11-15 09:00"]
    assert next_after(until, utc(2026, 11, 15, 17), DENVER) is None
    assert next_after(until, utc(2027, 5, 1), DENVER) is None


def test_a_count_becomes_the_day_of_the_last_one() -> None:
    sundays = Repeat("weekly", 1, datetime(2026, 11, 1, 9, 0), (SUN,))
    assert until_after(sundays, 6) == date(2026, 12, 6)
    assert until_after(sundays, 1) == date(2026, 11, 1)
    plain = Repeat("daily", 1, datetime(2026, 11, 1, 9, 0))
    assert until_after(plain, 3) == date(2026, 11, 3)
    ended = Repeat("weekly", 1, datetime(2026, 11, 1, 9, 0), (SUN,), None, until_after(sundays, 6))
    assert local_days(ended, utc(2026, 12, 1), 1) == ["Sun 2026-12-06 09:00"]
    assert next_after(ended, utc(2026, 12, 7), DENVER) is None


def test_a_count_is_refused_when_out_of_range_or_the_rule_already_ends() -> None:
    sundays = Repeat("weekly", 1, datetime(2026, 11, 1, 9, 0), (SUN,))
    for count in (0, MAX_COUNT + 1):
        with pytest.raises(ValueError):
            until_after(sundays, count)
    with pytest.raises(ValueError):
        until_after(Repeat("weekly", 1, datetime(2026, 11, 1, 9, 0), (SUN,), None, date(2026, 12, 1)), 2)


def test_a_wall_time_is_kept_across_the_change_forward_and_back() -> None:
    weekdays = Repeat("weekly", 1, datetime(2027, 3, 11, 8, 0), (MON, TUE, WED, THU, FRI))
    fri = instant(weekdays.anchor, DENVER)
    assert fri == utc(2027, 3, 11, 15, 0)
    mon = next_after(weekdays, fri, DENVER)
    assert mon == utc(2027, 3, 12, 15, 0)
    after_change = next_after(weekdays, utc(2027, 3, 13), DENVER)
    assert after_change == utc(2027, 3, 15, 14, 0)
    back = Repeat("weekly", 1, datetime(2027, 11, 5, 8, 0), (MON, FRI))
    assert instant(back.anchor, DENVER) == utc(2027, 11, 5, 14, 0)
    assert next_after(back, instant(back.anchor, DENVER), DENVER) == utc(2027, 11, 8, 15, 0)


def test_a_weekday_wall_time_the_clocks_skip_fires_an_hour_later_and_one_they_repeat_fires_once() -> None:
    skipped = Repeat("weekly", 1, datetime(2027, 3, 12, 2, 30), (FRI, SUN))
    assert next_after(skipped, utc(2027, 3, 13), DENVER) == utc(2027, 3, 14, 9, 30)
    repeated = Repeat("weekly", 1, datetime(2027, 11, 5, 1, 30), (FRI, SUN))
    got = next_of(repeated, utc(2027, 11, 6), DENVER)
    assert got == utc(2027, 11, 7, 7, 30)
    assert next_after(repeated, got, DENVER) == utc(2027, 11, 12, 8, 30)


def test_a_missed_run_of_weekday_occurrences_collapses_to_the_next_one_after_now() -> None:
    weekdays = Repeat("weekly", 1, datetime(2026, 1, 5, 8, 0), (MON, TUE, WED, THU, FRI))
    assert next_after(weekdays, utc(2026, 11, 13, 20), DENVER) == utc(2026, 11, 16, 15, 0)


@pytest.mark.parametrize("repeat", [
    Repeat("weekly", 1, datetime(2026, 11, 2, 8, 0), (MON, WED)),
    Repeat("monthly", 3, datetime(2026, 11, 2, 8, 0), (MON,), 1, date(2027, 6, 1)),
    Repeat("daily", 1, datetime(2026, 11, 2, 8, 0), (), None, date(2026, 12, 1)),
])
def test_the_stored_form_reads_back_as_itself(repeat: Repeat) -> None:
    assert from_json(to_json(repeat)) == repeat


def test_a_rule_without_the_new_fields_is_stored_exactly_as_it_was() -> None:
    old = Repeat("monthly", 1, datetime(2026, 10, 1, 9, 0))
    assert to_json(old) == {"freq": "monthly", "every": 1, "anchor": "2026-10-01T09:00"}
    assert from_json({"freq": "monthly", "every": 1, "anchor": "2026-10-01T09:00"}) == old


@pytest.mark.parametrize("args", [
    ("daily", 1, (MON,), None, None), ("yearly", 1, (MON,), None, None), ("weekly", 1, (SUN, MON), None, None),
    ("weekly", 1, (MON, MON), None, None), ("weekly", 1, (7,), None, None), ("weekly", 1, (MON,), 1, None),
    ("monthly", 1, (MON,), None, None), ("monthly", 1, (MON,), 5, None), ("monthly", 1, (MON,), 0, None),
    ("monthly", 1, (), 1, None), ("weekly", 1, (MON,), None, date(2026, 10, 1)),
])
def test_a_rule_that_does_not_make_sense_is_refused(args: tuple[str, int, tuple[int, ...], int | None, date | None]) -> None:
    freq, every, weekdays, nth, until = args
    chosen = freq_of(freq)
    assert chosen is not None
    with pytest.raises(ValueError):
        Repeat(chosen, every, datetime(2026, 11, 2, 8, 0), weekdays, nth, until)


@pytest.mark.parametrize("raw", [
    {"freq": "weekly", "every": 1, "anchor": "2026-11-02T08:00", "weekdays": "mon"},
    {"freq": "weekly", "every": 1, "anchor": "2026-11-02T08:00", "extra": 1},
    {"freq": "weekly", "every": 1, "anchor": "2026-11-02T08:00", "until": 5},
    {"freq": "weekly", "every": 1, "anchor": "2026-11-02T08:00", "until": "tomorrow"},
])
def test_a_stored_form_that_to_json_does_not_make_is_refused(raw: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        from_json(raw)
