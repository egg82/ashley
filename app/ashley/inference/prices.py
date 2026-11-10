"""What a call cost, from the published per-million-token prices in `prices.json` (each provider's entry names its
source page and the date it was read). A model with no entry has no price: its cost is unknown, never zero."""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from importlib import resources
from typing import Any

from .model import Usage


@dataclass(frozen=True)
class Tier:
    """USD per million tokens for prompts of at most `up_to_prompt_tokens` (None: no upper bound). A prompt's length
    counts input, cache-read and cache-write tokens. `cache_write` is the price of a write at the cache lifetime the
    provider is asked for (Anthropic's 5 minutes, OpenAI's 30)."""

    up_to_prompt_tokens: int | None
    input: Decimal
    cache_write: Decimal
    cache_read: Decimal
    output: Decimal


@dataclass(frozen=True)
class Period:
    """The tiers in force from `starts` through `ends`, both inclusive UTC dates, None leaving that side open: a
    promotion is one period and the price after it another."""

    starts: date | None
    ends: date | None
    tiers: tuple[Tier, ...]

    def covers(self, on: date) -> bool:
        return (self.starts is None or self.starts <= on) and (self.ends is None or on <= self.ends)


@dataclass(frozen=True)
class Prices:
    """`by_model[provider][model]` is that model's periods, which never overlap; each period's tiers ascend by
    `up_to_prompt_tokens`, the last unbounded."""

    by_model: Mapping[str, Mapping[str, tuple[Period, ...]]]

    def cost_usd(self, provider: str, model: str, usage: Usage, on: date) -> Decimal | None:
        """The cost of one call made on `on` (UTC), priced in the period covering that date at the first tier whose
        bound holds its whole prompt (each request is priced on its own); None when the provider or model has no
        entry or no period covers `on`."""
        periods = self.by_model.get(provider, {}).get(model, ())
        tiers = next((p.tiers for p in periods if p.covers(on)), None)
        if tiers is None:
            return None
        prompt = usage.input_tokens + usage.cache_read_tokens + usage.cache_write_tokens
        tier = next(t for t in tiers if t.up_to_prompt_tokens is None or prompt <= t.up_to_prompt_tokens)
        total = (usage.input_tokens * tier.input + usage.cache_write_tokens * tier.cache_write
                 + usage.cache_read_tokens * tier.cache_read + usage.output_tokens * tier.output)
        return total.scaleb(-6)


def load() -> Prices:
    """The prices shipped in `prices.json` beside this module (`parse`)."""
    text = resources.files("ashley.inference").joinpath("prices.json").read_text()
    return parse(json.loads(text, parse_float=Decimal))


def parse(data: object) -> Prices:
    """Prices from JSON already parsed: `{"<provider>": {"source": url, "read_on": "YYYY-MM-DD", "models":
    {"<model>": [{"from"?: "YYYY-MM-DD", "until"?: "YYYY-MM-DD", "tiers": [{"up_to_prompt_tokens": n | null,
    "input": n, "cache_write": n, "cache_read": n, "output": n}, ...]}, ...]}}}`. A model has at least one period;
    a period without `from` or `until` is open on that side, `from` <= `until`, and no two periods of a model share
    a date. Prices are finite and >= 0, given as JSON numbers and held exactly as their decimal text; tiers ascend
    and only the last is unbounded. Raises ValueError naming what is wrong."""
    providers = _object("prices", data)
    return Prices({name: _provider(name, entry) for name, entry in providers.items()})


def _provider(name: str, entry: object) -> dict[str, tuple[Period, ...]]:
    fields = _object(name, entry)
    if set(fields) != {"source", "read_on", "models"}:
        raise ValueError(f"{name}: expected exactly source, read_on and models")
    source = fields["source"]
    if not isinstance(source, str) or not source.strip():
        raise ValueError(f"{name}.source: expected a non-empty string")
    _date(f"{name}.read_on", fields["read_on"])
    models = _object(f"{name}.models", fields["models"])
    return {model: _periods(f"{name}.{model}", periods) for model, periods in models.items()}


def _date(where: str, value: object) -> date:
    try:
        if not isinstance(value, str) or len(value) != 10:
            raise ValueError
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"{where}: expected YYYY-MM-DD") from None


def _periods(where: str, entries: object) -> tuple[Period, ...]:
    items = _list(entries)
    if not items:
        raise ValueError(f"{where}: expected a non-empty list of periods")
    periods = tuple(_period(f"{where}[{i}]", item) for i, item in enumerate(items))
    ordered = sorted(periods, key=lambda p: p.starts or date.min)
    if any((a.ends or date.max) >= (b.starts or date.min) for a, b in zip(ordered, ordered[1:])):
        raise ValueError(f"{where}: periods overlap")
    return periods


def _period(where: str, entry: object) -> Period:
    fields = _object(where, entry)
    unknown = sorted(set(fields) - {"from", "until", "tiers"})
    if unknown or "tiers" not in fields:
        raise ValueError(f"{where}: expected tiers and optionally from and until")
    starts = _date(f"{where}.from", fields["from"]) if "from" in fields else None
    ends = _date(f"{where}.until", fields["until"]) if "until" in fields else None
    if starts and ends and starts > ends:
        raise ValueError(f"{where}: from is after until")
    return Period(starts, ends, _tiers(where, fields["tiers"]))


def _tiers(where: str, entries: object) -> tuple[Tier, ...]:
    items = _list(entries)
    if not items:
        raise ValueError(f"{where}: expected a non-empty list of tiers")
    tiers = tuple(_tier(f"{where}[{i}]", item) for i, item in enumerate(items))
    bounds = [t.up_to_prompt_tokens for t in tiers]
    if bounds[-1] is not None or any(b is None for b in bounds[:-1]):
        raise ValueError(f"{where}: only the last tier is unbounded")
    finite = [b for b in bounds if b is not None]
    if any(a >= b for a, b in zip(finite, finite[1:])):
        raise ValueError(f"{where}: tiers must ascend by up_to_prompt_tokens")
    return tiers


def _tier(where: str, entry: object) -> Tier:
    fields = _object(where, entry)
    if set(fields) != {"up_to_prompt_tokens", "input", "cache_write", "cache_read", "output"}:
        raise ValueError(f"{where}: expected exactly up_to_prompt_tokens, input, cache_write, cache_read, output")
    bound = fields["up_to_prompt_tokens"]
    if bound is not None and (isinstance(bound, bool) or not isinstance(bound, int) or bound <= 0):
        raise ValueError(f"{where}.up_to_prompt_tokens: expected a whole number above 0 or null")
    return Tier(bound, *(_price(f"{where}.{k}", fields[k]) for k in ("input", "cache_write", "cache_read", "output")))


def _price(where: str, value: object) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, int | float | Decimal):
        raise ValueError(f"{where}: expected a number")
    price = Decimal(repr(value)) if isinstance(value, float) else Decimal(value)
    if not price.is_finite() or price < 0:
        raise ValueError(f"{where}: expected a finite number of 0 or more")
    return price


def _object(where: str, value: object) -> dict[str, object]:
    raw: Any = value
    if not hasattr(raw, "keys") or not all(type(key) is str for key in raw.keys()):
        raise ValueError(f"{where}: expected an object")
    return dict[str, object](raw)


def _list(value: object) -> list[object]:
    """The items of a JSON array, empty when `value` is not one."""
    raw: Any = value
    return list[object](raw) if _is_list(value) else []


def _is_list(value: object) -> bool:
    return isinstance(value, list)
