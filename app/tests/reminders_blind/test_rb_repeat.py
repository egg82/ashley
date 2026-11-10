"""`ashley.senses.repeat`: occurrences keep the household's wall time across daylight saving, a monthly or yearly one
falls on the anchor's day or the month's last, a skipped wall time is read with the offset before the change and a
repeated one is its first instant, and a repeat round-trips through JSON."""

from collections.abc import Callable
from typing import Any
from datetime import UTC, datetime, timedelta

import pytest
from ashley.senses.repeat import Repeat, from_json, instant, to_json
from repeat_support import next_of as next_after
from rb_support import ZONE


HOURLY: Any = "hourly"


def utc(y: int, mo: int, d: int, h: int = 0, mi: int = 0) -> datetime:
    return datetime(y, mo, d, h, mi, tzinfo=UTC)


def walk(repeat: Repeat, n: int, start: datetime) -> list[datetime]:
    out: list[datetime] = []
    after = start
    for _ in range(n):
        after = next_after(repeat, after, ZONE)
        out.append(after)
    return out


def months(first_year: int, first_month: int, n: int) -> list[tuple[int, int]]:
    return [((first_year * 12 + first_month - 1 + k) // 12, (first_year * 12 + first_month - 1 + k) % 12 + 1) for k in range(n)]


def test_the_first_of_every_month_is_the_first_across_three_years_of_daylight_saving() -> None:
    repeat = Repeat("monthly", 1, datetime(2026, 1, 1, 9, 0))
    got = walk(repeat, 36, utc(2025, 12, 1))
    want = [instant(datetime(y, m, 1, 9, 0), ZONE) for y, m in months(2026, 1, 36)]
    assert got == want
    assert len(set(got)) == 36 and got == sorted(got)


def test_the_first_at_nine_is_nine_local_in_winter_and_summer() -> None:
    repeat = Repeat("monthly", 1, datetime(2026, 1, 1, 9, 0))
    got = walk(repeat, 12, utc(2025, 12, 1))
    assert [g.astimezone(ZONE).strftime("%d %H:%M") for g in got] == ["01 09:00"] * 12
    assert got[0] == utc(2026, 1, 1, 16)
    assert got[3] == utc(2026, 4, 1, 15)
    assert got[10] == utc(2026, 11, 1, 16)


def test_the_month_before_and_after_each_clock_change_is_neither_skipped_nor_doubled() -> None:
    repeat = Repeat("monthly", 1, datetime(2026, 1, 1, 9, 0))
    assert next_after(repeat, utc(2026, 3, 1, 16), ZONE) == utc(2026, 4, 1, 15)
    assert next_after(repeat, utc(2026, 3, 1, 15, 59), ZONE) == utc(2026, 3, 1, 16)
    assert next_after(repeat, utc(2026, 10, 1, 15), ZONE) == utc(2026, 11, 1, 16)
    assert next_after(repeat, utc(2026, 11, 1, 16), ZONE) == utc(2026, 12, 1, 16)


def test_strictly_after_never_returns_the_instant_asked_from() -> None:
    repeat = Repeat("daily", 1, datetime(2026, 3, 1, 9, 0))
    first = next_after(repeat, utc(2026, 1, 1), ZONE)
    assert first == utc(2026, 3, 1, 16)
    assert next_after(repeat, first, ZONE) == utc(2026, 3, 2, 16)
    assert next_after(repeat, first - timedelta(microseconds=1), ZONE) == first


def test_before_the_anchor_the_first_occurrence_is_the_anchor() -> None:
    repeat = Repeat("weekly", 1, datetime(2026, 6, 5, 18, 30))
    assert next_after(repeat, utc(2020, 1, 1), ZONE) == instant(datetime(2026, 6, 5, 18, 30), ZONE)


def test_the_thirty_first_falls_on_the_last_day_of_a_shorter_month_and_the_thirty_first_again_after() -> None:
    repeat = Repeat("monthly", 1, datetime(2026, 1, 31, 9, 0))
    got = [g.astimezone(ZONE) for g in walk(repeat, 14, utc(2026, 1, 1))]
    assert [(g.year, g.month, g.day) for g in got] == [
        (2026, 1, 31), (2026, 2, 28), (2026, 3, 31), (2026, 4, 30), (2026, 5, 31), (2026, 6, 30), (2026, 7, 31),
        (2026, 8, 31), (2026, 9, 30), (2026, 10, 31), (2026, 11, 30), (2026, 12, 31), (2027, 1, 31), (2027, 2, 28)]
    assert {(g.hour, g.minute) for g in got} == {(9, 0)}


def test_the_thirty_first_in_a_leap_year_february_is_the_twenty_ninth() -> None:
    repeat = Repeat("monthly", 1, datetime(2027, 12, 31, 9, 0))
    got = [g.astimezone(ZONE) for g in walk(repeat, 4, utc(2027, 12, 1))]
    assert [(g.year, g.month, g.day) for g in got] == [(2027, 12, 31), (2028, 1, 31), (2028, 2, 29), (2028, 3, 31)]


def test_every_n_months_steps_n_months_from_the_anchor() -> None:
    repeat = Repeat("monthly", 3, datetime(2026, 1, 15, 8, 0))
    got = [g.astimezone(ZONE) for g in walk(repeat, 5, utc(2026, 1, 1))]
    assert [(g.year, g.month, g.day) for g in got] == [(2026, 1, 15), (2026, 4, 15), (2026, 7, 15), (2026, 10, 15), (2027, 1, 15)]


def test_a_month_end_anchor_does_not_drift_after_a_short_month() -> None:
    repeat = Repeat("monthly", 1, datetime(2026, 1, 30, 9, 0))
    got = [g.astimezone(ZONE) for g in walk(repeat, 4, utc(2026, 1, 1))]
    assert [(g.month, g.day) for g in got] == [(1, 30), (2, 28), (3, 30), (4, 30)]


def test_daily_keeps_the_wall_time_across_both_clock_changes() -> None:
    repeat = Repeat("daily", 1, datetime(2026, 3, 6, 9, 0))
    got = walk(repeat, 4, utc(2026, 3, 6))
    assert [g.astimezone(ZONE).strftime("%m-%d %H:%M") for g in got] == ["03-06 09:00", "03-07 09:00", "03-08 09:00", "03-09 09:00"]
    assert got[2] - got[1] == timedelta(hours=23)
    back = walk(Repeat("daily", 1, datetime(2026, 10, 31, 9, 0)), 3, utc(2026, 10, 30))
    assert [g.astimezone(ZONE).strftime("%m-%d %H:%M") for g in back] == ["10-31 09:00", "11-01 09:00", "11-02 09:00"]
    assert back[2] - back[1] == timedelta(hours=24)
    assert back[1] - back[0] == timedelta(hours=25)


def test_every_three_days_and_every_two_weeks_step_by_that_many() -> None:
    days = walk(Repeat("daily", 3, datetime(2026, 3, 1, 12, 0)), 4, utc(2026, 2, 1))
    assert [g.astimezone(ZONE).strftime("%m-%d") for g in days] == ["03-01", "03-04", "03-07", "03-10"]
    weeks = walk(Repeat("weekly", 2, datetime(2026, 3, 1, 12, 0)), 3, utc(2026, 2, 1))
    assert [g.astimezone(ZONE).strftime("%m-%d") for g in weeks] == ["03-01", "03-15", "03-29"]


def test_a_weekly_reminder_stays_on_its_weekday_across_the_change() -> None:
    got = walk(Repeat("weekly", 1, datetime(2026, 3, 4, 7, 0)), 4, utc(2026, 3, 1))
    assert {g.astimezone(ZONE).weekday() for g in got} == {datetime(2026, 3, 4).weekday()}
    assert {g.astimezone(ZONE).hour for g in got} == {7}


def test_a_leap_day_yearly_is_the_28th_in_other_years_and_the_29th_in_the_next_leap_year() -> None:
    got = [g.astimezone(ZONE) for g in walk(Repeat("yearly", 1, datetime(2024, 2, 29, 10, 0)), 5, utc(2024, 1, 1))]
    assert [(g.year, g.month, g.day) for g in got] == [(2024, 2, 29), (2025, 2, 28), (2026, 2, 28), (2027, 2, 28), (2028, 2, 29)]


def test_a_yearly_keeps_its_wall_time_through_winter_and_summer() -> None:
    got = walk(Repeat("yearly", 1, datetime(2026, 7, 4, 9, 0)), 3, utc(2026, 1, 1))
    assert [g.astimezone(ZONE).strftime("%Y-%m-%d %H:%M") for g in got] == ["2026-07-04 09:00", "2027-07-04 09:00", "2028-07-04 09:00"]
    assert got[0] == utc(2026, 7, 4, 15)


def test_a_wall_time_the_clocks_skip_is_read_with_the_offset_before_the_change() -> None:
    skipped = datetime(2026, 3, 8, 2, 30)
    assert instant(skipped, ZONE) == utc(2026, 3, 8, 9, 30)
    assert instant(skipped, ZONE).astimezone(ZONE).strftime("%H:%M") == "03:30"
    repeat = Repeat("daily", 1, datetime(2026, 3, 7, 2, 30))
    got = walk(repeat, 3, utc(2026, 3, 7))
    assert got == [utc(2026, 3, 7, 9, 30), utc(2026, 3, 8, 9, 30), utc(2026, 3, 9, 8, 30)]


def test_a_wall_time_the_clocks_repeat_is_its_first_instant() -> None:
    twice = datetime(2026, 11, 1, 1, 30)
    assert instant(twice, ZONE) == utc(2026, 11, 1, 7, 30)
    repeat = Repeat("daily", 1, datetime(2026, 10, 31, 1, 30))
    assert walk(repeat, 3, utc(2026, 10, 31)) == [utc(2026, 10, 31, 7, 30), utc(2026, 11, 1, 7, 30), utc(2026, 11, 2, 8, 30)]


def test_instant_of_an_ordinary_wall_time_is_that_time_in_the_zone() -> None:
    assert instant(datetime(2026, 1, 15, 9, 0), ZONE) == utc(2026, 1, 15, 16)
    assert instant(datetime(2026, 7, 15, 9, 0), ZONE) == utc(2026, 7, 15, 15)
    assert instant(datetime(2026, 7, 15, 9, 0), ZONE).utcoffset() == timedelta(0)


@pytest.mark.parametrize("repeat", [
    Repeat("daily", 1, datetime(2026, 3, 1, 9, 0)), Repeat("weekly", 2, datetime(2026, 3, 1, 9, 30)),
    Repeat("monthly", 3, datetime(2026, 1, 31, 23, 59)), Repeat("yearly", 1000, datetime(2024, 2, 29, 0, 0))])
def test_a_repeat_round_trips_through_json(repeat: Repeat) -> None:
    raw = to_json(repeat)
    assert from_json(raw) == repeat
    assert from_json(dict(raw)) == repeat


def test_the_json_of_a_repeat_is_plain_data() -> None:
    import json

    raw = to_json(Repeat("monthly", 2, datetime(2026, 1, 31, 9, 0)))
    assert json.loads(json.dumps(raw)) == raw


def test_json_that_to_json_does_not_make_is_a_value_error() -> None:
    good = to_json(Repeat("monthly", 2, datetime(2026, 1, 31, 9, 0)))
    broken: list[dict[str, object]] = [{}, {"freq": "monthly"}, {**good, "extra": 1}]
    freq_key = next(k for k, v in good.items() if v == "monthly")
    broken.append({**good, freq_key: "hourly"})
    broken.append({**good, freq_key: 5})
    for key in good:
        broken.append({k: v for k, v in good.items() if k != key})
    every_key = next(k for k, v in good.items() if v == 2)
    broken.append({**good, every_key: "two"})
    every_key = next(k for k, v in good.items() if v == 2)
    for zero in (0, -1, 1001):
        broken.append({**good, every_key: zero})
    for raw in broken:
        with pytest.raises(ValueError):
            from_json(raw)


@pytest.mark.parametrize("make", [
    lambda: Repeat(HOURLY, 1, datetime(2026, 3, 1, 9, 0)),
    lambda: Repeat("daily", 0, datetime(2026, 3, 1, 9, 0)),
    lambda: Repeat("daily", 1001, datetime(2026, 3, 1, 9, 0)),
    lambda: Repeat("daily", 1, datetime(2026, 3, 1, 9, 0, tzinfo=UTC))])
def test_a_repeat_that_is_not_one_is_a_value_error(make: Callable[[], Repeat]) -> None:
    with pytest.raises(ValueError):
        make()
