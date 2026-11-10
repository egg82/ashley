"""`Repeat` weekdays, nth weekday and until at fixed dates read off a calendar: the first Monday and the last Friday of
a year, months with four and five of a weekday, the daylight-saving changes in Denver against Phoenix (which has none),
an end that is inclusive and a local day, and what a rule refuses."""

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest
from ashley.senses.repeat import MAX_COUNT, Repeat, from_json, instant, next_after, starts, to_json, until_after

DENVER, PHOENIX, LONDON = ZoneInfo("America/Denver"), ZoneInfo("America/Phoenix"), ZoneInfo("Europe/London")
MON, TUE, WED, THU, FRI, SAT, SUN = range(7)


def utc(y: int, mo: int, d: int, h: int = 0, mi: int = 0) -> datetime:
    return datetime(y, mo, d, h, mi, tzinfo=UTC)


def dates(repeat: Repeat, zone: ZoneInfo, n: int, after: datetime | None = None) -> list[date]:
    out: list[date] = []
    at = utc(2000, 1, 1) if after is None else after
    for _ in range(n):
        got = next_after(repeat, at, zone)
        if got is None:
            break
        out.append(got.astimezone(zone).date())
        at = got
    return out


def monthly(wd: int, nth: int, anchor: datetime = datetime(2026, 1, 1, 9, 0), until: date | None = None) -> Repeat:
    return Repeat("monthly", 1, anchor, (wd,), nth, until)


def test_the_first_monday_of_each_month_of_2026() -> None:
    got = dates(monthly(MON, 1), DENVER, 12)
    assert got == [date(2026, m, d) for m, d in [(1, 5), (2, 2), (3, 2), (4, 6), (5, 4), (6, 1), (7, 6), (8, 3), (9, 7), (10, 5), (11, 2), (12, 7)]]


def test_the_last_friday_of_each_month_of_2026_is_the_fifth_where_there_is_one() -> None:
    got = dates(monthly(FRI, -1), DENVER, 12)
    assert got == [date(2026, m, d) for m, d in [(1, 30), (2, 27), (3, 27), (4, 24), (5, 29), (6, 26), (7, 31), (8, 28), (9, 25), (10, 30), (11, 27), (12, 25)]]


def test_the_fourth_friday_is_not_the_last_in_a_month_with_five() -> None:
    got = dates(monthly(FRI, 4), DENVER, 12)
    assert got[4] == date(2026, 5, 22) and got[6] == date(2026, 7, 24) and got[9] == date(2026, 10, 23)
    assert all(g.weekday() == FRI and 22 <= g.day <= 28 for g in got)


def test_a_month_with_exactly_four_of_a_weekday_has_its_last_as_its_fourth() -> None:
    feb = Repeat("monthly", 1, datetime(2026, 2, 1, 9, 0), (MON,), -1)
    assert dates(feb, DENVER, 1) == [date(2026, 2, 23)]
    assert dates(monthly(MON, 4, datetime(2026, 2, 1, 9, 0)), DENVER, 1) == [date(2026, 2, 23)]


def test_a_leap_february_with_five_tuesdays_has_its_last_on_the_29th() -> None:
    last = Repeat("monthly", 1, datetime(2028, 2, 1, 9, 0), (TUE,), -1)
    fourth = Repeat("monthly", 1, datetime(2028, 2, 1, 9, 0), (TUE,), 4)
    assert dates(last, DENVER, 1) == [date(2028, 2, 29)]
    assert dates(fourth, DENVER, 1) == [date(2028, 2, 22)]


def test_an_anchor_after_the_months_nth_weekday_starts_in_the_next_month() -> None:
    repeat = monthly(MON, 1, datetime(2026, 1, 20, 9, 0))
    assert starts(repeat) == datetime(2026, 2, 2, 9, 0)
    assert dates(repeat, DENVER, 2) == [date(2026, 2, 2), date(2026, 3, 2)]


def test_an_anchor_on_the_nth_weekday_itself_is_the_first_occurrence() -> None:
    repeat = monthly(MON, 1, datetime(2026, 1, 5, 9, 0))
    assert starts(repeat) == datetime(2026, 1, 5, 9, 0)
    assert dates(repeat, DENVER, 1) == [date(2026, 1, 5)]


def test_the_starting_instant_itself_is_not_after_itself() -> None:
    repeat = monthly(MON, 1, datetime(2026, 1, 5, 9, 0))
    first = instant(datetime(2026, 1, 5, 9, 0), DENVER)
    assert next_after(repeat, first, DENVER) == instant(datetime(2026, 2, 2, 9, 0), DENVER)


def test_weekly_on_weekdays_starts_on_the_first_named_day_on_or_after_the_anchor() -> None:
    work = (MON, TUE, WED, THU, FRI)
    saturday = Repeat("weekly", 1, datetime(2026, 11, 7, 8, 0), work)
    assert starts(saturday) == datetime(2026, 11, 9, 8, 0)
    wednesday = Repeat("weekly", 1, datetime(2026, 11, 4, 8, 0), (MON, WED))
    assert starts(wednesday) == datetime(2026, 11, 4, 8, 0)
    thursday = Repeat("weekly", 1, datetime(2026, 11, 5, 8, 0), (MON, WED))
    assert starts(thursday) == datetime(2026, 11, 9, 8, 0)


def test_every_weekday_is_five_a_week_and_skips_the_weekend() -> None:
    repeat = Repeat("weekly", 1, datetime(2026, 11, 2, 8, 0), (MON, TUE, WED, THU, FRI))
    got = dates(repeat, DENVER, 10)
    assert got == [date(2026, 11, d) for d in (2, 3, 4, 5, 6, 9, 10, 11, 12, 13)]


def test_every_other_week_runs_one_week_and_skips_the_next_and_weeks_start_on_monday() -> None:
    repeat = Repeat("weekly", 2, datetime(2026, 11, 2, 8, 0), (MON, SUN))
    assert dates(repeat, DENVER, 5) == [date(2026, 11, 2), date(2026, 11, 8), date(2026, 11, 16), date(2026, 11, 22), date(2026, 11, 30)]


def test_a_sunday_belongs_to_the_week_that_began_on_the_monday_before_it() -> None:
    repeat = Repeat("weekly", 2, datetime(2026, 11, 8, 8, 0), (SUN,))
    assert dates(repeat, DENVER, 3) == [date(2026, 11, 8), date(2026, 11, 22), date(2026, 12, 6)]


def test_until_is_the_last_local_day_inclusive() -> None:
    mondays = Repeat("weekly", 1, datetime(2026, 11, 2, 9, 0), (MON,), None, date(2026, 11, 16))
    assert dates(mondays, DENVER, 10) == [date(2026, 11, 2), date(2026, 11, 9), date(2026, 11, 16)]
    short = Repeat("weekly", 1, datetime(2026, 11, 2, 9, 0), (MON,), None, date(2026, 11, 15))
    assert dates(short, DENVER, 10) == [date(2026, 11, 2), date(2026, 11, 9)]


def test_an_occurrence_late_on_the_last_day_is_allowed_though_its_utc_day_is_the_next() -> None:
    weekly = Repeat("weekly", 1, datetime(2026, 11, 2, 23, 30), (MON,), None, date(2026, 11, 9))
    got = next_after(weekly, instant(datetime(2026, 11, 2, 23, 30), DENVER), DENVER)
    assert got == utc(2026, 11, 10, 6, 30)
    assert got is not None and got.astimezone(DENVER).date() == date(2026, 11, 9)
    assert next_after(weekly, got, DENVER) is None


def test_the_walk_ends_with_none_and_stays_ended() -> None:
    repeat = Repeat("weekly", 1, datetime(2026, 11, 2, 9, 0), (MON,), None, date(2026, 11, 2))
    first = next_after(repeat, utc(2026, 1, 1), DENVER)
    assert first is not None and first == instant(datetime(2026, 11, 2, 9, 0), DENVER)
    assert next_after(repeat, first, DENVER) is None
    assert next_after(repeat, utc(2030, 1, 1), DENVER) is None


def test_an_until_before_the_first_named_day_leaves_no_occurrence() -> None:
    repeat = Repeat("weekly", 1, datetime(2026, 11, 3, 9, 0), (MON,), None, date(2026, 11, 8))
    assert starts(repeat) is None
    assert next_after(repeat, utc(2026, 1, 1), DENVER) is None


def test_a_monthly_rule_ends_at_until_as_well() -> None:
    repeat = monthly(MON, 1, until=date(2026, 3, 2))
    assert dates(repeat, DENVER, 10) == [date(2026, 1, 5), date(2026, 2, 2), date(2026, 3, 2)]
    assert dates(monthly(MON, 1, until=date(2026, 3, 1)), DENVER, 10) == [date(2026, 1, 5), date(2026, 2, 2)]


def test_a_daily_and_a_plain_monthly_rule_may_end_too() -> None:
    daily = Repeat("daily", 1, datetime(2026, 11, 1, 7, 0), until=date(2026, 11, 3))
    assert dates(daily, DENVER, 10) == [date(2026, 11, 1), date(2026, 11, 2), date(2026, 11, 3)]
    plain = Repeat("monthly", 1, datetime(2026, 1, 31, 7, 0), until=date(2026, 3, 30))
    assert dates(plain, DENVER, 10) == [date(2026, 1, 31), date(2026, 2, 28)]


def test_weekdays_keep_the_wall_time_across_the_spring_change_in_denver_and_not_in_phoenix() -> None:
    work = Repeat("weekly", 1, datetime(2026, 3, 6, 8, 0), (MON, TUE, WED, THU, FRI))
    denver = [next_after(work, a, DENVER) for a in (utc(2026, 3, 6, 15), utc(2026, 3, 6, 16))]
    assert denver == [utc(2026, 3, 9, 14), utc(2026, 3, 9, 14)]
    assert next_after(work, utc(2026, 3, 6, 14), DENVER) == utc(2026, 3, 6, 15)
    assert next_after(work, utc(2026, 3, 6, 14), PHOENIX) == utc(2026, 3, 6, 15)
    assert next_after(work, utc(2026, 3, 6, 15), PHOENIX) == utc(2026, 3, 9, 15)


def test_the_last_sunday_of_march_at_nine_is_nine_local_in_denver_and_phoenix() -> None:
    repeat = monthly(SUN, -1, datetime(2026, 3, 1, 9, 0))
    assert next_after(repeat, utc(2026, 3, 1), DENVER) == utc(2026, 3, 29, 15)
    assert next_after(repeat, utc(2026, 3, 1), PHOENIX) == utc(2026, 3, 29, 16)
    assert next_after(repeat, utc(2026, 3, 29, 15), DENVER) == utc(2026, 4, 26, 15)


def test_the_first_sunday_of_november_at_nine_is_nine_local_after_the_clocks_go_back() -> None:
    repeat = monthly(SUN, 1, datetime(2026, 10, 1, 9, 0))
    assert next_after(repeat, utc(2026, 10, 1), DENVER) == utc(2026, 10, 4, 15)
    assert next_after(repeat, utc(2026, 10, 4, 15), DENVER) == utc(2026, 11, 1, 16)
    assert next_after(repeat, utc(2026, 10, 4, 16), PHOENIX) == utc(2026, 11, 1, 16)


def test_a_weekly_sunday_time_the_clocks_skip_fires_an_hour_later_in_wall_terms() -> None:
    repeat = Repeat("weekly", 1, datetime(2026, 3, 1, 2, 30), (SUN,))
    assert next_after(repeat, utc(2026, 3, 1, 9, 30), DENVER) == utc(2026, 3, 8, 9, 30)
    assert utc(2026, 3, 8, 9, 30).astimezone(DENVER).strftime("%H:%M") == "03:30"
    assert next_after(repeat, utc(2026, 3, 8, 9, 30), DENVER) == utc(2026, 3, 15, 8, 30)


def test_a_monthly_nth_weekday_time_the_clocks_repeat_is_its_first_instant() -> None:
    repeat = monthly(SUN, 1, datetime(2026, 10, 1, 1, 30))
    assert next_after(repeat, utc(2026, 10, 5), DENVER) == utc(2026, 11, 1, 7, 30)
    assert next_after(repeat, utc(2026, 10, 5), LONDON) == utc(2026, 11, 1, 1, 30)


def test_london_weekdays_keep_the_wall_time_across_the_last_sunday_of_march_and_october() -> None:
    work = Repeat("weekly", 1, datetime(2026, 3, 27, 8, 0), (MON, FRI))
    assert next_after(work, utc(2026, 3, 27, 8), LONDON) == utc(2026, 3, 30, 7)
    assert next_after(work, utc(2026, 3, 20), LONDON) == utc(2026, 3, 27, 8)
    autumn = Repeat("weekly", 1, datetime(2026, 10, 23, 8, 0), (MON, FRI))
    assert next_after(autumn, utc(2026, 10, 23, 7), LONDON) == utc(2026, 10, 26, 8)


def test_until_after_gives_the_day_of_the_nth_occurrence_with_weekdays() -> None:
    sundays = Repeat("weekly", 1, datetime(2026, 11, 2, 18, 0), (SUN,))
    assert until_after(sundays, 1) == date(2026, 11, 8)
    assert until_after(sundays, 6) == date(2026, 12, 13)
    both = Repeat("weekly", 1, datetime(2026, 11, 2, 18, 0), (MON, SUN))
    assert [until_after(both, c) for c in (1, 2, 3, 4)] == [date(2026, 11, 2), date(2026, 11, 8), date(2026, 11, 9), date(2026, 11, 15)]
    assert until_after(monthly(MON, 1), 3) == date(2026, 3, 2)


def test_until_after_refuses_a_count_outside_one_to_the_most_and_a_rule_with_its_own_end() -> None:
    sundays = Repeat("weekly", 1, datetime(2026, 11, 2, 18, 0), (SUN,))
    for bad in (0, -1, MAX_COUNT + 1):
        with pytest.raises(ValueError):
            until_after(sundays, bad)
    with pytest.raises(ValueError):
        until_after(Repeat("weekly", 1, datetime(2026, 11, 2, 18, 0), (SUN,), None, date(2027, 1, 1)), 2)
    assert until_after(sundays, MAX_COUNT) > until_after(sundays, MAX_COUNT - 1)


def test_weekdays_on_a_daily_or_yearly_rule_are_refused() -> None:
    anchor = datetime(2026, 11, 2, 9, 0)
    with pytest.raises(ValueError):
        Repeat("daily", 1, anchor, (MON,))
    with pytest.raises(ValueError):
        Repeat("yearly", 1, anchor, (MON,))
    assert Repeat("weekly", 1, anchor, (MON,)).weekdays == (MON,)
    assert Repeat("monthly", 1, anchor, (MON,), 1).nth == 1


@pytest.mark.parametrize("nth", [0, 5, -2, 6, 100])
def test_an_nth_other_than_one_to_four_or_the_last_is_refused(nth: int) -> None:
    with pytest.raises(ValueError):
        Repeat("monthly", 1, datetime(2026, 1, 1, 9, 0), (MON,), nth)


@pytest.mark.parametrize("weekdays", [(7,), (-1,), (3, 1), (0, 9), (2, 2), (0, 4, 4)])
def test_a_weekday_outside_monday_to_sunday_or_out_of_order_is_refused(weekdays: tuple[int, ...]) -> None:
    with pytest.raises(ValueError):
        Repeat("weekly", 1, datetime(2026, 1, 1, 9, 0), weekdays)


def test_nth_belongs_to_a_monthly_rule_on_weekdays_only() -> None:
    with pytest.raises(ValueError):
        Repeat("weekly", 1, datetime(2026, 1, 1, 9, 0), (MON,), 1)
    with pytest.raises(ValueError):
        Repeat("monthly", 1, datetime(2026, 1, 1, 9, 0), (), 1)
    with pytest.raises(ValueError):
        Repeat("daily", 1, datetime(2026, 1, 1, 9, 0), (), 1)


def test_a_monthly_rule_on_two_weekdays_gives_each_ones_nth_in_date_order() -> None:
    both = Repeat("monthly", 1, datetime(2026, 1, 1, 9, 0), (MON, FRI), 1)
    assert dates(both, DENVER, 5) == [date(2026, 1, 2), date(2026, 1, 5), date(2026, 2, 2), date(2026, 2, 6), date(2026, 3, 2)]
    last = Repeat("monthly", 1, datetime(2026, 1, 1, 9, 0), (MON, FRI), -1)
    assert dates(last, DENVER, 4) == [date(2026, 1, 26), date(2026, 1, 30), date(2026, 2, 23), date(2026, 2, 27)]


def test_a_plain_rule_is_stored_with_no_field_it_does_not_use() -> None:
    plain = to_json(Repeat("monthly", 1, datetime(2026, 1, 31, 9, 0)))
    assert not {"weekdays", "nth", "until"} & set(plain)
    shaped = to_json(monthly(FRI, -1, until=date(2027, 1, 1)))
    assert {"weekdays", "nth", "until"} <= set(shaped)


@pytest.mark.parametrize("change", [{"freq": "daily"}, {"freq": "yearly"}, {"nth": 0}, {"nth": 7}, {"weekdays": [7]}, {"weekdays": [4, 1]},
                                    {"until": "not-a-date"}, {"until": 20270101}, {"weekdays": "mon"}])
def test_what_to_json_does_not_make_is_refused_when_read_back(change: dict[str, object]) -> None:
    raw = dict(to_json(monthly(FRI, -1, until=date(2027, 1, 1))))
    raw.update(change)
    with pytest.raises(ValueError):
        from_json(raw)
