"""The spans the spend page reports, across a month boundary and a time zone behind UTC."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from ashley.inference.spend_windows import windows

DENVER = ZoneInfo("America/Denver")


def starts(now: datetime, zone: ZoneInfo) -> dict[str, datetime]:
    return {w.name: w.starts.astimezone(UTC) for w in windows(now, zone)}


def test_local_midnights_hold_while_utc_is_already_in_the_next_month() -> None:
    now = datetime(2026, 12, 1, 3, 0, tzinfo=UTC)   # Nov 30, 20:00 in Denver
    got = starts(now, DENVER)
    assert got["today"] == datetime(2026, 11, 30, 7, 0, tzinfo=UTC)
    assert got["week"] == datetime(2026, 11, 24, 7, 0, tzinfo=UTC)
    assert got["month"] == datetime(2026, 11, 1, 6, 0, tzinfo=UTC)   # still MDT on Nov 1: UTC-6, DST ended that night


def test_the_same_instant_is_a_new_month_in_utc() -> None:
    now = datetime(2026, 12, 1, 3, 0, tzinfo=UTC)
    got = starts(now, ZoneInfo("UTC"))
    assert got["month"] == datetime(2026, 12, 1, tzinfo=UTC)
    assert got["today"] == got["month"]


def test_a_week_across_a_daylight_saving_change_is_calendar_days_not_168_hours() -> None:
    now = datetime(2026, 11, 3, 18, 0, tzinfo=UTC)   # Denver: DST ended Nov 1, so the span holds a 25-hour day
    got = starts(now, DENVER)
    assert got["week"] == datetime(2026, 10, 28, 6, 0, tzinfo=UTC)
    assert got["today"] == datetime(2026, 11, 3, 7, 0, tzinfo=UTC)


def test_a_week_that_starts_in_the_previous_month_still_ends_in_this_one() -> None:
    now = datetime(2026, 3, 3, 12, 0, tzinfo=UTC)
    got = starts(now, ZoneInfo("UTC"))
    assert got["week"] == datetime(2026, 2, 25, tzinfo=UTC) and got["month"] == datetime(2026, 3, 1, tzinfo=UTC)
