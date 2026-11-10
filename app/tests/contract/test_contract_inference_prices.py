"""`prices.parse` (shape, exact decimals, every documented rejection), `Prices.cost_usd` (tiers, the prompt-length rule
counting cache tokens, exact arithmetic, None for the unknown) and the shipped `prices.load()`."""

import copy
import json
import math
from collections.abc import Callable
from decimal import Decimal

import pytest
from ashley.inference.model import Usage
from ashley.inference.prices import Period, Prices, Tier, parse
from hypothesis import given, settings
from hypothesis import strategies as st
from prices_support import D, Data, cost, period, priced, table, tier, tiers_of


def test_a_table_parses_to_decimal_tiers_in_order() -> None:
    data = table(tier(200_000, 1.25, 1.5, 0.125, 10), tier(None, 2.5, 3, 0.25, 15))
    data["beta"] = {"source": "https://example.test/b", "read_on": "2026-01-02", "models": {"x": [period(tier(None))]}}
    parsed = parse(data)
    assert set(parsed.by_model) == {"alpha", "beta"}
    assert parsed.by_model["alpha"]["m1"] == (Period(None, None, (
        Tier(200_000, D("1.25"), D("1.5"), D("0.125"), D("10")),
        Tier(None, D("2.5"), D("3"), D("0.25"), D("15")),
    )),)
    assert isinstance(parsed.by_model["alpha"]["m1"], tuple)
    assert isinstance(parsed.by_model["alpha"]["m1"][0].tiers, tuple)
    assert parsed.by_model["beta"]["x"] == (Period(None, None, (Tier(None, D("3"), D("3.75"), D("0.3"), D("15")),)),)


def test_prices_are_held_as_their_decimal_text_not_as_binary_floats() -> None:
    parsed = parse(json.loads(json.dumps(table(tier(None, 0.1, 0.3, 0.07, 1.1)))))
    only = tiers_of(parsed)[0]
    assert (only.input, only.cache_write, only.cache_read, only.output) == (D("0.1"), D("0.3"), D("0.07"), D("1.1"))
    assert str(only.input) == "0.1"


@given(st.lists(st.decimals(min_value=0, max_value=5000, places=4, allow_nan=False, allow_infinity=False),
                min_size=4, max_size=4))
@settings(max_examples=60)
def test_any_price_written_in_decimal_text_is_held_exactly(values: list[Decimal]) -> None:
    text = json.dumps(table(tier(None, "I", "W", "R", "O"))).replace('"I"', str(values[0])).replace(
        '"W"', str(values[1])).replace('"R"', str(values[2])).replace('"O"', str(values[3]))
    only = tiers_of(parse(json.loads(text)))[0]
    assert (only.input, only.cache_write, only.cache_read, only.output) == tuple(values)


def test_zero_is_a_price_and_a_free_model_costs_zero_not_unknown() -> None:
    free = priced(tier(None, 0, 0, 0, 0))
    assert cost(free, Usage(10, 10, 10, 10)) == D(0)
    assert cost(free, Usage(10, 10, 10, 10)) is not None


def mutate(where: Callable[[Data], tuple[Data, str]], value: object) -> Callable[[Data], None]:
    def apply(data: Data) -> None:
        holder, key = where(data)
        holder[key] = value
    return apply


def in_tier(key: str) -> Callable[[Data], tuple[Data, str]]:
    return lambda d: (d["alpha"]["models"]["m1"][0]["tiers"][0], key)


def at_provider(key: str) -> Callable[[Data], tuple[Data, str]]:
    return lambda d: (d["alpha"], key)


BAD_PRICES: list[object] = [-1, -0.01, True, "3", None, math.nan, math.inf, -math.inf, [3], {"p": 3}]
REJECTIONS: dict[str, Callable[[Data], None]] = {
    **{f"{k} {v!r}": mutate(in_tier(k), v) for k in ("input", "cache_write", "cache_read", "output")
       for v in BAD_PRICES},
    **{f"up_to {v!r}": mutate(in_tier("up_to_prompt_tokens"), v) for v in (1.5, "5", True, [5], math.nan)},
    "source missing": lambda d: d["alpha"].pop("source"),
    "read_on missing": lambda d: d["alpha"].pop("read_on"),
    "models missing": lambda d: d["alpha"].pop("models"),
    "provider extra key": lambda d: d["alpha"].__setitem__("note", "x"),
    "read_on not a date": mutate(at_provider("read_on"), "yesterday"),
    "read_on a month 13": mutate(at_provider("read_on"), "2026-13-01"),
    "read_on a number": mutate(at_provider("read_on"), 20261025),
    "models not an object": mutate(at_provider("models"), [tier(None)]),
    "model with no periods": lambda d: d["alpha"]["models"].__setitem__("m1", []),
    "periods not a list": lambda d: d["alpha"]["models"].__setitem__("m1", period()),
    "period not an object": lambda d: d["alpha"]["models"].__setitem__("m1", [5]),
    "period with no tiers": lambda d: d["alpha"]["models"]["m1"][0].__setitem__("tiers", []),
    "period without tiers key": lambda d: d["alpha"]["models"]["m1"][0].pop("tiers"),
    "tiers not a list": lambda d: d["alpha"]["models"]["m1"][0].__setitem__("tiers", tier(None)),
    "period extra key": lambda d: d["alpha"]["models"]["m1"][0].__setitem__("note", "x"),
    "tier not an object": lambda d: d["alpha"]["models"]["m1"][0].__setitem__("tiers", [5]),
    "tier missing input": lambda d: d["alpha"]["models"]["m1"][0]["tiers"][0].pop("input"),
    "tier missing cache_write": lambda d: d["alpha"]["models"]["m1"][0]["tiers"][0].pop("cache_write"),
    "tier missing cache_read": lambda d: d["alpha"]["models"]["m1"][0]["tiers"][0].pop("cache_read"),
    "tier missing output": lambda d: d["alpha"]["models"]["m1"][0]["tiers"][0].pop("output"),
    "tier missing its bound": lambda d: d["alpha"]["models"]["m1"][0]["tiers"][0].pop("up_to_prompt_tokens"),
    "tier extra key": lambda d: d["alpha"]["models"]["m1"][0]["tiers"][0].__setitem__("batch", 1),
    "the only tier bounded": lambda d: d["alpha"]["models"]["m1"][0]["tiers"][0].__setitem__("up_to_prompt_tokens", 1000),
}


@pytest.mark.parametrize("change", REJECTIONS.values(), ids=REJECTIONS.keys())
def test_every_documented_rejection_raises_value_error(change: Callable[[Data], None]) -> None:
    data = table()
    change(data)
    with pytest.raises(ValueError):
        parse(data)


BAD_TIERINGS: dict[str, Data] = {
    "last tier bounded": table(tier(10), tier(20)),
    "unbounded tier first": table(tier(None), tier(500)),
    "equal bounds": table(tier(500), tier(500), tier(None)),
    "descending bounds": table(tier(900), tier(500), tier(None)),
    "two unbounded tiers": table(tier(None), tier(None)),
}


@pytest.mark.parametrize("data", BAD_TIERINGS.values(), ids=BAD_TIERINGS.keys())
def test_tiers_must_ascend_and_only_the_last_is_unbounded(data: Data) -> None:
    with pytest.raises(ValueError):
        parse(data)


@pytest.mark.parametrize("data", [None, [], "prices", 5, [table()]])
def test_a_table_that_is_not_an_object_is_refused(data: object) -> None:
    with pytest.raises(ValueError):
        parse(data)


def test_the_rejections_have_valid_twins() -> None:
    """Controls: the shapes the refusals above are one change away from are accepted."""
    parse(table(tier(None, 0, 0, 0, 0)))
    parse(table(tier(10), tier(20), tier(None)))
    two = table(tier(500), tier(None))
    two["alpha"]["models"]["m2"] = [period(tier(None))]
    parse(copy.deepcopy(two))


# --- cost_usd -----------------------------------------------------------------------------------------------------


def test_cost_adds_the_four_prices_per_million_tokens_exactly() -> None:
    assert cost(priced(tier(None)), Usage(1000, 500, 200, 100)) == D("0.010935")


@pytest.mark.parametrize(("usage", "expected"), [
    (Usage(1_000_000, 0, 0, 0), D("3")),
    (Usage(0, 1_000_000, 0, 0), D("15")),
    (Usage(0, 0, 1_000_000, 0), D("0.3")),
    (Usage(0, 0, 0, 1_000_000), D("3.75")),
    (Usage(1, 0, 0, 0), D("0.000003")),
    (Usage(0, 1, 0, 0), D("0.000015")),
    (Usage(0, 0, 1, 0), D("0.0000003")),
    (Usage(0, 0, 0, 1), D("0.00000375")),
    (Usage(0, 0, 0, 0), D(0)),
])
def test_each_kind_of_token_has_its_own_price(usage: Usage, expected: Decimal) -> None:
    assert cost(priced(tier(None)), usage) == expected


def test_the_cost_is_a_decimal_that_is_never_rounded() -> None:
    result = cost(priced(tier(None, 1.234567, 0, 0, 0)), Usage(1, 0, 0, 0))
    assert isinstance(result, Decimal)
    assert result == D("0.000001234567")
    assert cost(priced(tier(None, 0.1, 0, 0, 0)), Usage(3, 0, 0, 0)) == D("0.0000003")
    assert cost(priced(tier(None, 0.000001, 0, 0, 0)), Usage(1, 0, 0, 0)) == D("0.000000000001")


@given(st.integers(0, 10**7), st.integers(0, 10**7), st.integers(0, 10**7), st.integers(0, 10**7),
       st.lists(st.decimals(min_value=0, max_value=1000, places=3, allow_nan=False, allow_infinity=False),
                min_size=4, max_size=4))
@settings(max_examples=60)
def test_a_single_tier_cost_is_the_exact_sum_over_a_million(i: int, o: int, r: int, w: int, p: list[Decimal]) -> None:
    text = json.dumps(table(tier(None, "I", "W", "R", "O"))).replace('"I"', str(p[0])).replace(
        '"W"', str(p[1])).replace('"R"', str(p[2])).replace('"O"', str(p[3]))
    got = cost(parse(json.loads(text)), Usage(i, o, r, w))
    assert got == (i * p[0] + w * p[1] + r * p[2] + o * p[3]) / 1_000_000


TWO = (tier(200_000, 1, 1.5, 0.1, 10), tier(None, 2, 3, 0.2, 20))


@pytest.mark.parametrize(("usage", "expected"), [
    (Usage(200_000, 0, 0, 0), D("0.2")),
    (Usage(200_001, 0, 0, 0), D("0.400002")),
    (Usage(1, 0, 0, 0), D("0.000001")),
    (Usage(0, 0, 200_000, 0), D("0.02")),
    (Usage(0, 0, 200_001, 0), D("0.0400002")),
    (Usage(0, 0, 0, 200_000), D("0.3")),
    (Usage(0, 0, 0, 200_001), D("0.600003")),
    (Usage(100_000, 0, 60_000, 40_000), D("0.166")),
    (Usage(100_001, 0, 60_000, 40_000), D("0.332002")),
    (Usage(100_000, 0, 60_000, 40_001), D("0.332003")),
    (Usage(100_000, 0, 60_001, 40_000), D("0.3320002")),
    (Usage(10, 5_000_000, 0, 0), D("50.00001")),
])
def test_the_tier_is_chosen_by_the_whole_prompt_including_cache_tokens_and_never_by_output(
        usage: Usage, expected: Decimal) -> None:
    """Tiers: up to 200,000 prompt tokens (input 1, cache write 1.5, cache read 0.1, output 10), then (2, 3, 0.2, 20).
    The tier the whole prompt falls in prices every token of the request."""
    assert cost(priced(*TWO), usage) == expected


def test_three_tiers_pick_the_first_whose_bound_holds_the_prompt() -> None:
    three = priced(tier(100, 1, 0, 0, 0), tier(1000, 2, 0, 0, 0), tier(None, 3, 0, 0, 0))
    assert [cost(three, Usage(n, 0, 0, 0)) for n in (1, 100, 101, 1000, 1001, 10**6)] == [
        D("0.000001"), D("0.0001"), D("0.000202"), D("0.002"), D("0.003003"), D("3")]


def test_unknown_providers_and_models_have_no_cost_not_zero() -> None:
    prices = priced(tier(None))
    usage = Usage(1000, 500)
    assert cost(prices, usage) is not None
    assert cost(prices, usage, provider="beta") is None
    assert cost(prices, usage, model="m2") is None
    assert cost(prices, usage, provider="beta", model="m2") is None
    assert cost(prices, usage, model="") is None
    assert cost(Prices({}), usage) is None


def test_a_model_is_priced_under_its_own_provider_only() -> None:
    data = table()
    data["beta"] = {"source": "https://example.test/b", "read_on": "2026-10-25",
                    "models": {"m1": [period(tier(None, 6, 0, 0, 0))], "only-beta": [period(tier(None, 9, 0, 0, 0))]}}
    prices = parse(data)
    usage = Usage(1_000_000, 0)
    assert cost(prices, usage, "alpha", "m1") == D(3)
    assert cost(prices, usage, "beta", "m1") == D(6)
    assert cost(prices, usage, "alpha", "only-beta") is None
