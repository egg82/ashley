"""Builders shared by the prices contract suites: price tables as JSON data, and costing a usage under them."""

from datetime import date
from decimal import Decimal
from typing import Any

from ashley.inference.model import Usage
from ashley.inference.prices import Prices, Tier, parse


Data = dict[str, Any]
D = Decimal


def tier(up_to: int | None, inp: object = 3, write: object = 3.75, read: object = 0.3, out: object = 15) -> Data:
    return {"up_to_prompt_tokens": up_to, "input": inp, "cache_write": write, "cache_read": read, "output": out}


ON = date(2026, 10, 25)


def period(*tiers: Data, starts: str | None = None, until: str | None = None) -> Data:
    made: Data = {"tiers": list(tiers or (tier(None),))}
    if starts is not None:
        made["from"] = starts
    if until is not None:
        made["until"] = until
    return made


def of_periods(*periods: Data) -> Data:
    return {"alpha": {"source": "https://example.test/pricing", "read_on": "2026-10-25",
                      "models": {"m1": list(periods or (period(),))}}}


def table(*tiers: Data) -> Data:
    """One open period holding `tiers`."""
    return of_periods(period(*tiers))


def priced(*tiers: Data) -> Prices:
    return parse(table(*tiers))


def cost(prices: Prices, usage: Usage, provider: str = "alpha", model: str = "m1", on: date = ON) -> Decimal | None:
    return prices.cost_usd(provider, model, usage, on)


def tiers_of(prices: Prices, provider: str = "alpha", model: str = "m1") -> tuple[Tier, ...]:
    return prices.by_model[provider][model][0].tiers
