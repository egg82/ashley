"""`prices` periods (dated, inclusive, open sides, no overlap) and the shipped `prices.load()`."""

import itertools
import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from ashley.inference import prices as prices_module
from ashley.inference.model import Usage
from ashley.inference.prices import Period, Tier, load, parse
from hypothesis import given, settings
from hypothesis import strategies as st
from prices_support import D, ON, Data, cost, of_periods, period, tier


# --- periods ------------------------------------------------------------------------------------------------------

D1 = date(2026, 11, 30)
D2 = date(2026, 12, 1)
ONE_M = Usage(1_000_000, 0)


def at(per_million: int) -> Data:
    """A tier pricing only input, at `per_million` USD."""
    return tier(None, per_million, 0, 0, 0)


def test_periods_parse_to_dates_with_open_sides_as_none() -> None:
    parsed = parse(of_periods(
        period(at(1), until="2026-11-30"), period(at(2), starts="2026-12-01", until="2026-12-31"),
        period(at(3), starts="2027-01-01")))
    assert set(parsed.by_model["alpha"]["m1"]) == {
        Period(None, date(2026, 11, 30), (Tier(None, D(1), D(0), D(0), D(0)),)),
        Period(date(2026, 12, 1), date(2026, 12, 31), (Tier(None, D(2), D(0), D(0), D(0)),)),
        Period(date(2027, 1, 1), None, (Tier(None, D(3), D(0), D(0), D(0)),)),
    }
    assert len(parsed.by_model["alpha"]["m1"]) == 3


def test_a_period_covers_its_dates_inclusively_and_open_sides_reach_forever() -> None:
    tiers = (Tier(None, D(1), D(0), D(0), D(0)),)
    closed = Period(D1, D2, tiers)
    assert [closed.covers(date(2026, 11, 29)), closed.covers(D1), closed.covers(D2),
            closed.covers(date(2026, 12, 2))] == [False, True, True, False]
    assert Period(D1, D1, tiers).covers(D1) and not Period(D1, D1, tiers).covers(D2)
    assert Period(None, D1, tiers).covers(date(1990, 1, 1)) and Period(None, D1, tiers).covers(D1)
    assert not Period(None, D1, tiers).covers(D2)
    assert Period(D2, None, tiers).covers(date(2999, 1, 1)) and Period(D2, None, tiers).covers(D2)
    assert not Period(D2, None, tiers).covers(D1)
    assert Period(None, None, tiers).covers(date(1, 1, 1)) and Period(None, None, tiers).covers(date(9999, 12, 31))


def test_each_date_is_priced_in_the_period_covering_it_with_both_ends_inclusive() -> None:
    prices = parse(of_periods(period(at(1), until="2026-11-30"), period(at(2), starts="2026-12-01")))
    days = (date(2020, 1, 1), date(2026, 11, 29), D1, D2, date(2026, 12, 2), date(2099, 1, 1))
    assert [cost(prices, ONE_M, on=d) for d in days] == [D(1), D(1), D(1), D(2), D(2), D(2)]


def test_listing_the_periods_in_any_order_prices_the_same() -> None:
    forward = parse(of_periods(period(at(1), until="2026-11-30"), period(at(2), starts="2026-12-01")))
    backward = parse(of_periods(period(at(2), starts="2026-12-01"), period(at(1), until="2026-11-30")))
    for d in (date(2026, 1, 1), D1, D2, date(2027, 1, 1)):
        assert cost(forward, ONE_M, on=d) == cost(backward, ONE_M, on=d)


def test_a_date_no_period_covers_has_no_cost_not_zero() -> None:
    prices = parse(of_periods(period(at(1), until="2026-10-31"), period(at(2), starts="2026-12-01")))
    assert cost(prices, ONE_M, on=date(2026, 10, 31)) == D(1)
    assert cost(prices, ONE_M, on=date(2026, 11, 1)) is None
    assert cost(prices, ONE_M, on=D1) is None
    assert cost(prices, ONE_M, on=D2) == D(2)


def test_a_period_open_on_one_side_prices_everything_on_that_side_only() -> None:
    later = parse(of_periods(period(at(5), starts="2026-12-01")))
    earlier = parse(of_periods(period(at(5), until="2026-11-30")))
    assert [cost(later, ONE_M, on=d) for d in (D1, D2, date(2999, 1, 1))] == [None, D(5), D(5)]
    assert [cost(earlier, ONE_M, on=d) for d in (D1, D2, date(1999, 1, 1))] == [D(5), None, D(5)]


def test_a_one_day_period_is_valid_and_covers_only_that_day() -> None:
    prices = parse(of_periods(period(at(7), starts="2026-12-01", until="2026-12-01")))
    assert [cost(prices, ONE_M, on=d) for d in (D1, D2, date(2026, 12, 2))] == [None, D(7), None]


def test_each_period_has_its_own_tiers() -> None:
    prices = parse(of_periods(
        period(tier(1000, 1, 0, 0, 0), tier(None, 2, 0, 0, 0), until="2026-11-30"),
        period(tier(None, 9, 0, 0, 0), starts="2026-12-01")))
    assert cost(prices, Usage(1000, 0), on=D1) == D("0.001")
    assert cost(prices, Usage(1001, 0), on=D1) == D("0.002002")
    assert cost(prices, Usage(1001, 0), on=D2) == D("0.009009")


def test_usage_is_priced_on_the_date_asked_across_providers_and_models() -> None:
    data = of_periods(period(at(1), until="2026-11-30"), period(at(2), starts="2026-12-01"))
    data["alpha"]["models"]["flat"] = [period(at(4))]
    data["beta"] = {"source": "https://example.test/b", "read_on": "2026-10-25", "models": {"m1": [period(at(8))]}}
    prices = parse(data)
    asked = [("alpha", "m1", D1), ("alpha", "m1", D2), ("alpha", "flat", D1), ("alpha", "flat", D2), ("beta", "m1", D1)]
    assert [cost(prices, ONE_M, p, m, on=d) for p, m, d in asked] == [D(1), D(2), D(4), D(4), D(8)]


BAD_PERIODS: dict[str, Data] = {
    "sharing the boundary day": of_periods(period(at(1), until="2026-11-30"), period(at(2), starts="2026-11-30")),
    "a period inside another": of_periods(period(at(1), starts="2026-11-01", until="2026-11-30"),
                                          period(at(2), starts="2026-11-10", until="2026-11-20")),
    "identical": of_periods(period(at(1), starts="2026-11-01", until="2026-11-30"),
                            period(at(2), starts="2026-11-01", until="2026-11-30")),
    "two open on both sides": of_periods(period(at(1)), period(at(2))),
    "open on both sides and another": of_periods(period(at(1)), period(at(2), starts="2026-11-01")),
    "both open to the past": of_periods(period(at(1), until="2026-11-01"), period(at(2), until="2026-12-01")),
    "both open to the future": of_periods(period(at(1), starts="2026-11-01"), period(at(2), starts="2026-12-01")),
    "overlap listed out of order": of_periods(period(at(2), starts="2026-11-30"), period(at(1), until="2026-12-05")),
    "overlap in the last pair": of_periods(period(at(1), until="2026-10-31"),
                                           period(at(2), starts="2026-12-01", until="2026-12-31"),
                                           period(at(3), starts="2026-12-31")),
    "from after until": of_periods(period(at(1), starts="2026-12-01", until="2026-11-30")),
    "from not a date": of_periods(period(at(1), starts="soon")),
    "until not a date": of_periods(period(at(1), until="2026-02-30")),
}


@pytest.mark.parametrize("data", BAD_PERIODS.values(), ids=BAD_PERIODS.keys())
def test_overlapping_or_backwards_or_undated_periods_are_refused(data: Data) -> None:
    with pytest.raises(ValueError):
        parse(data)


def with_period_key(key: str, value: object) -> Data:
    data = of_periods(period(at(1)))
    data["alpha"]["models"]["m1"][0][key] = value
    return data


@pytest.mark.parametrize("key", ["from", "until"])
@pytest.mark.parametrize("value", [20261201, None, True, ["2026-12-01"], "2026/12/01", ""])
def test_a_period_bound_that_is_not_a_date_string_is_refused(key: str, value: object) -> None:
    with pytest.raises(ValueError):
        parse(with_period_key(key, value))


def test_the_period_refusals_have_valid_twins() -> None:
    """Controls: periods that touch without sharing a day, a one-day period and a gap are accepted."""
    parse(of_periods(period(at(1), until="2026-11-29"), period(at(2), starts="2026-11-30")))
    parse(of_periods(period(at(1), starts="2026-12-01", until="2026-12-01")))
    parse(of_periods(period(at(1), until="2026-10-01"), period(at(2), starts="2026-12-01")))
    parse(with_period_key("from", "2026-12-01"))
    parse(with_period_key("until", "2026-12-01"))


@given(st.lists(st.tuples(st.integers(0, 30), st.integers(0, 5)), min_size=1, max_size=6), st.integers(-5, 400))
@settings(max_examples=80)
def test_a_random_run_of_dated_periods_prices_each_day_in_the_period_holding_it(
        runs: list[tuple[int, int]], query: int) -> None:
    """Periods of `length` days, each followed by a gap of `gap` days; period i prices input at i + 1 USD."""
    base = date(2026, 1, 1).toordinal()
    periods: list[Data] = []
    spans: list[tuple[int, int]] = []
    cursor = 0
    for i, (length, gap) in enumerate(runs):
        first, last = cursor, cursor + length
        periods.append(period(at(i + 1), starts=date.fromordinal(base + first).isoformat(),
                              until=date.fromordinal(base + last).isoformat()))
        spans.append((first, last))
        cursor = last + 1 + gap
    prices = parse(of_periods(*reversed(periods)))
    want = next((D(i + 1) for i, (first, last) in enumerate(spans) if first <= query <= last), None)
    assert cost(prices, ONE_M, on=date.fromordinal(base + query)) == want


# --- the shipped prices -------------------------------------------------------------------------------------------


def shipped() -> Any:
    return json.loads(Path(prices_module.__file__).with_name("prices.json").read_text(encoding="utf-8"))


def test_load_is_the_shipped_file_parsed() -> None:
    assert load() == parse(shipped())


def test_the_shipped_prices_are_non_empty_ordered_dated_without_overlap_and_name_their_source() -> None:
    prices = load()
    assert prices.by_model, "no provider is priced"
    for provider, models in prices.by_model.items():
        assert models, f"{provider} prices no model"
        entry = shipped()[provider]
        assert str(entry["source"]).startswith("http"), provider
        assert len(str(entry["read_on"])) == 10, provider
        for model, periods in models.items():
            assert periods, f"{provider}/{model} has no periods"
            for a, b in itertools.combinations(periods, 2):
                assert not overlap(a, b), f"{provider}/{model} has overlapping periods"
            for per in periods:
                assert per.starts is None or per.ends is None or per.starts <= per.ends
                tiers = per.tiers
                assert tiers and tiers[-1].up_to_prompt_tokens is None
                bounds = [t.up_to_prompt_tokens for t in tiers[:-1]]
                assert all(b is not None for b in bounds)
                assert bounds == sorted(set(b for b in bounds if b is not None))
                for t in tiers:
                    assert min(t.input, t.cache_write, t.cache_read, t.output) >= 0


def overlap(a: Period, b: Period) -> bool:
    lo = max(a.starts or date.min, b.starts or date.min)
    hi = min(a.ends or date.max, b.ends or date.max)
    return lo <= hi


def test_every_shipped_model_prices_a_call_in_each_of_its_periods() -> None:
    prices = load()
    for provider, models in prices.by_model.items():
        for model, periods in models.items():
            for per in periods:
                on = per.starts or per.ends or ON
                got = prices.cost_usd(provider, model, Usage(1000, 1000, 1000, 1000), on)
                assert got is not None and got >= 0, f"{provider}/{model} on {on}"
