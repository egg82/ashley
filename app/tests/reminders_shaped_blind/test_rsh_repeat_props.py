"""`Repeat` with weekdays, an nth weekday of the month and an end, as properties of its stated contract: every occurrence
is on a named day, keeps the anchor's wall time in the zone, comes strictly after the one before, never passes `until`;
the nth weekday is in the right month in the right week of it, however many such weekdays the month has; a count's end
is the day of that occurrence. An independent calendar oracle gives the dates."""

import calendar
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from ashley.senses.repeat import Repeat, from_json, next_after, occurrence, starts, to_json, until_after
from hypothesis import given, settings
from hypothesis import strategies as st

ZONES = [ZoneInfo(z) for z in ("America/Phoenix", "America/Denver", "Europe/London")]
SAFE_TIMES = [(0, 0), (5, 30), (9, 0), (12, 15), (15, 0), (20, 45), (23, 30)]
FAST = settings(max_examples=40, deadline=None)

zones = st.sampled_from(ZONES)
times = st.sampled_from(SAFE_TIMES)
days = st.dates(date(2025, 1, 1), date(2031, 12, 31))
day_sets = st.lists(st.integers(0, 6), min_size=1, max_size=7, unique=True).map(lambda xs: tuple(sorted(xs)))
nths = st.sampled_from([1, 2, 3, 4, -1])


def at(day: date, hm: tuple[int, int]) -> datetime:
    return datetime(day.year, day.month, day.day, hm[0], hm[1])


def walk(repeat: Repeat, zone: ZoneInfo, n: int) -> list[datetime]:
    """The next `n` occurrences as UTC instants, asked for one after the other from a day before the anchor."""
    out: list[datetime] = []
    after = (repeat.anchor - timedelta(days=1)).replace(tzinfo=zone).astimezone(UTC)
    for _ in range(n):
        got = next_after(repeat, after, zone)
        if got is None:
            break
        out.append(got)
        after = got
    return out


def nth_weekday(year: int, month: int, weekday: int, nth: int) -> date:
    firsts = [d for d in range(1, calendar.monthrange(year, month)[1] + 1) if date(year, month, d).weekday() == weekday]
    return date(year, month, firsts[nth - 1] if nth > 0 else firsts[-1])


def monday_of(day: date) -> date:
    return day - timedelta(days=day.weekday())


@FAST
@given(day=days, hm=times, zone=zones, wds=day_sets, every=st.integers(1, 3), n=st.integers(1, 14))
def test_weekly_occurrences_are_on_named_days_at_the_wall_time_and_strictly_increasing(
        day: date, hm: tuple[int, int], zone: ZoneInfo, wds: tuple[int, ...], every: int, n: int) -> None:
    repeat = Repeat("weekly", every, at(day, hm), wds)
    got = walk(repeat, zone, n)
    assert len(got) == n
    assert all(a < b for a, b in zip(got, got[1:]))
    for g in got:
        local = g.astimezone(zone)
        assert local.weekday() in wds
        assert (local.hour, local.minute) == hm
        assert local.replace(tzinfo=None) >= repeat.anchor


@FAST
@given(day=days, hm=times, zone=zones, wds=day_sets, n=st.integers(1, 14))
def test_weekly_every_week_is_every_named_day_on_or_after_the_anchor(
        day: date, hm: tuple[int, int], zone: ZoneInfo, wds: tuple[int, ...], n: int) -> None:
    repeat = Repeat("weekly", 1, at(day, hm), wds)
    want: list[date] = []
    d = day
    while len(want) < n:
        if d.weekday() in wds:
            want.append(d)
        d += timedelta(days=1)
    assert [g.astimezone(zone).date() for g in walk(repeat, zone, n)] == want


@FAST
@given(day=days, hm=times, zone=zones, wds=day_sets, every=st.integers(2, 4), n=st.integers(1, 14))
def test_weekly_every_other_week_counts_weeks_from_the_monday_of_the_anchors_week(
        day: date, hm: tuple[int, int], zone: ZoneInfo, wds: tuple[int, ...], every: int, n: int) -> None:
    monday = monday_of(day)
    repeat = Repeat("weekly", every, at(monday, hm), wds)
    want = [monday + timedelta(weeks=every * w, days=wd) for w in range(n) for wd in wds][:n]
    assert [g.astimezone(zone).date() for g in walk(repeat, zone, n)] == want


@FAST
@given(day=days, hm=times, zone=zones, wds=day_sets, every=st.integers(1, 2), span=st.integers(0, 60), n=st.integers(1, 20))
def test_no_occurrence_passes_until_and_the_walk_then_ends(
        day: date, hm: tuple[int, int], zone: ZoneInfo, wds: tuple[int, ...], every: int, span: int, n: int) -> None:
    until = day + timedelta(days=span)
    repeat = Repeat("weekly", every, at(day, hm), wds, None, until)
    got = walk(repeat, zone, n)
    assert all(g.astimezone(zone).date() <= until for g in got)
    if len(got) < n:
        last = got[-1] if got else (repeat.anchor - timedelta(days=1)).replace(tzinfo=zone).astimezone(UTC)
        assert next_after(repeat, last, zone) is None
        assert next_after(repeat, last + timedelta(days=400), zone) is None
    nobounds = Repeat("weekly", every, at(day, hm), wds)
    reachable = [g for g in walk(nobounds, zone, n) if g.astimezone(zone).date() <= until]
    assert got == reachable


@FAST
@given(day=days, hm=times, zone=zones, wd=st.integers(0, 6), nth=nths, n=st.integers(1, 14))
def test_the_nth_weekday_of_every_month_is_the_oracles_date(
        day: date, hm: tuple[int, int], zone: ZoneInfo, wd: int, nth: int, n: int) -> None:
    repeat = Repeat("monthly", 1, at(day, hm), (wd,), nth)
    want: list[date] = []
    index = day.year * 12 + day.month - 1
    while len(want) < n:
        found = nth_weekday(index // 12, index % 12 + 1, wd, nth)
        if found >= day:
            want.append(found)
        index += 1
    got = walk(repeat, zone, n)
    assert [g.astimezone(zone).date() for g in got] == want
    assert all((g.astimezone(zone).hour, g.astimezone(zone).minute) == hm for g in got)
    assert all(a < b for a, b in zip(got, got[1:]))


@FAST
@given(first=st.dates(date(2025, 1, 1), date(2031, 12, 1)), hm=times, zone=zones, wd=st.integers(0, 6), nth=nths,
       every=st.integers(2, 5), n=st.integers(1, 10))
def test_every_few_months_steps_by_whole_months_from_the_anchors_month(
        first: date, hm: tuple[int, int], zone: ZoneInfo, wd: int, nth: int, every: int, n: int) -> None:
    start = first.replace(day=1)
    repeat = Repeat("monthly", every, at(start, hm), (wd,), nth)
    index = start.year * 12 + start.month - 1
    want = [nth_weekday((index + every * k) // 12, (index + every * k) % 12 + 1, wd, nth) for k in range(n)]
    assert [g.astimezone(zone).date() for g in walk(repeat, zone, n)] == want


@FAST
@given(year=st.integers(2025, 2032), wd=st.integers(0, 6), nth=nths)
def test_the_nth_weekday_lands_in_its_own_month_and_week_of_it(year: int, wd: int, nth: int) -> None:
    repeat = Repeat("monthly", 1, datetime(year, 1, 1, 9, 0), (wd,), nth)
    got = walk(repeat, ZoneInfo("America/Denver"), 12)
    assert [g.astimezone(ZoneInfo("America/Denver")).month for g in got] == list(range(1, 13))
    for g in got:
        d = g.astimezone(ZoneInfo("America/Denver")).date()
        assert d.weekday() == wd
        size = calendar.monthrange(d.year, d.month)[1]
        if nth > 0:
            assert 7 * (nth - 1) < d.day <= 7 * nth
        else:
            assert d.day + 7 > size


@FAST
@given(day=days, hm=times, zone=zones, freq=st.sampled_from(["daily", "weekly"]), every=st.integers(1, 3), n=st.integers(1, 10))
def test_occurrence_k_of_a_rule_with_no_weekdays_is_the_kth_of_the_walk_and_k_zero_is_the_anchor(
        day: date, hm: tuple[int, int], zone: ZoneInfo, freq: str, every: int, n: int) -> None:
    repeat = Repeat("daily" if freq == "daily" else "weekly", every, at(day, hm))
    assert starts(repeat) == occurrence(repeat, 0) == repeat.anchor
    walked = [g.astimezone(zone).replace(tzinfo=None) for g in walk(repeat, zone, n)]
    assert [occurrence(repeat, k) for k in range(n)] == walked


@FAST
@given(first=st.dates(date(2025, 1, 1), date(2031, 12, 1)), hm=times, zone=zones, wd=st.integers(0, 6), nth=nths,
       n=st.integers(1, 12))
def test_monthly_occurrence_k_with_no_weekdays_is_the_kth_of_the_walk(
        first: date, hm: tuple[int, int], zone: ZoneInfo, wd: int, nth: int, n: int) -> None:
    repeat = Repeat("monthly", 1, at(first, hm))
    walked = [g.astimezone(zone).replace(tzinfo=None) for g in walk(repeat, zone, n)]
    assert [occurrence(repeat, k) for k in range(n)] == walked


@FAST
@given(day=days, hm=times, zone=zones, wds=day_sets, count=st.integers(1, 12))
def test_a_counts_end_is_the_day_of_that_occurrence_and_the_rule_then_runs_exactly_that_many_times(
        day: date, hm: tuple[int, int], zone: ZoneInfo, wds: tuple[int, ...], count: int) -> None:
    repeat = Repeat("weekly", 1, at(day, hm), wds)
    end = until_after(repeat, count)
    assert end == walk(repeat, zone, count)[-1].astimezone(zone).date()
    bounded = Repeat("weekly", 1, at(day, hm), wds, None, end)
    assert len(walk(bounded, zone, count + 3)) == count


@FAST
@given(day=days, hm=times, wds=day_sets, nth=nths, span=st.one_of(st.none(), st.integers(0, 900)), freq=st.sampled_from(["weekly", "monthly"]))
def test_the_rule_as_stored_reads_back_as_the_same_rule(
        day: date, hm: tuple[int, int], wds: tuple[int, ...], nth: int, span: int | None, freq: str) -> None:
    until = None if span is None else day + timedelta(days=span)
    repeat = Repeat("weekly", 2, at(day, hm), wds, None, until) if freq == "weekly" else Repeat("monthly", 3, at(day, hm), wds[:1], nth, until)
    assert from_json(to_json(repeat)) == repeat
