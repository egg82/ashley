"""A repeating reminder's next occurrence: wall-clock time kept across daylight saving in the household's zone, a
short month clamping the day without drifting it, a missed run of occurrences collapsing into the next one after now,
and the rule's stored form reading back as itself."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from ashley.senses.repeat import Repeat, from_json, instant, to_json
from repeat_support import next_of as next_after

DENVER = ZoneInfo("America/Denver")


def utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


def test_the_first_of_the_month_at_nine_stays_nine_local_across_the_change_back_and_forward() -> None:
    monthly = Repeat("monthly", 1, datetime(2026, 10, 1, 9, 0))
    oct_1 = instant(monthly.anchor, DENVER)
    assert oct_1 == utc(2026, 10, 1, 15, 0)
    nov_1 = next_after(monthly, oct_1, DENVER)
    assert nov_1 == utc(2026, 11, 1, 16, 0)
    dec_1 = next_after(monthly, nov_1, DENVER)
    assert dec_1 == utc(2026, 12, 1, 16, 0)
    assert next_after(monthly, utc(2027, 3, 20), DENVER) == utc(2027, 4, 1, 15, 0)


def test_a_daily_reminder_across_the_change_back_is_twenty_five_hours_apart_once() -> None:
    daily = Repeat("daily", 1, datetime(2026, 10, 31, 8, 0))
    first = instant(daily.anchor, DENVER)
    second = next_after(daily, first, DENVER)
    third = next_after(daily, second, DENVER)
    assert (second - first).total_seconds() == 25 * 3600
    assert (third - second).total_seconds() == 24 * 3600


def test_a_wall_time_the_change_forward_skips_fires_an_hour_later_and_a_repeated_one_fires_first() -> None:
    assert instant(datetime(2027, 3, 14, 2, 30), DENVER) == utc(2027, 3, 14, 9, 30)
    assert instant(datetime(2026, 11, 1, 1, 30), DENVER) == utc(2026, 11, 1, 7, 30)


def test_a_31st_is_the_months_last_day_when_shorter_and_the_31st_again_after() -> None:
    monthly = Repeat("monthly", 1, datetime(2027, 1, 31, 9, 0))
    feb = next_after(monthly, instant(monthly.anchor, DENVER), DENVER)
    mar = next_after(monthly, feb, DENVER)
    assert feb.astimezone(DENVER).date().isoformat() == "2027-02-28"
    assert mar.astimezone(DENVER).date().isoformat() == "2027-03-31"


def test_every_second_week_and_every_year_on_the_29th_of_february() -> None:
    fortnightly = Repeat("weekly", 2, datetime(2026, 11, 2, 7, 0))
    assert next_after(fortnightly, instant(fortnightly.anchor, DENVER), DENVER).astimezone(DENVER).day == 16
    leap = Repeat("yearly", 1, datetime(2028, 2, 29, 12, 0))
    assert next_after(leap, instant(leap.anchor, DENVER), DENVER).astimezone(DENVER).date().isoformat() == "2029-02-28"


def test_occurrences_missed_in_an_outage_collapse_into_the_first_after_now() -> None:
    monthly = Repeat("monthly", 1, datetime(2026, 11, 1, 9, 0))
    assert next_after(monthly, utc(2027, 2, 10, 12, 0), DENVER) == utc(2027, 3, 1, 16, 0)
    assert next_after(monthly, utc(2026, 1, 1), DENVER) == instant(monthly.anchor, DENVER)


def test_the_stored_form_reads_back_and_anything_else_is_refused() -> None:
    rule = Repeat("monthly", 3, datetime(2026, 11, 1, 9, 0))
    assert from_json(to_json(rule)) == rule
    for bad in ({"freq": "hourly", "every": 1, "anchor": "2026-11-01T09:00"},
                {"freq": "daily", "every": 0, "anchor": "2026-11-01T09:00"},
                {"freq": "daily", "every": 1, "anchor": "2026-11-01T09:00-07:00"},
                {"freq": "daily", "every": 1}):
        with pytest.raises(ValueError):
            from_json(bad)
