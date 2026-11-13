"""models.dev's `api.json` read into a `Catalogue` (https://models.dev): the only reader of its field names.

Its shape is `{"<provider>": {"name", "api"?, "models": {"<model>": {"name", "tool_call", "structured_output"?,
"limit": {"context", "output"}, "cost"?: {"input", "output", "cache_read"?, "cache_write"?, "tiers"?:
[{"input", ..., "tier": {"type": "context", "size": n}}], "context_over_200k"?: {...}}}}}}`, prices in USD per million
tokens. A model missing a price it lists is unpriced for that part, never 0.

Outside text: a provider or model this cannot read is left out and counted, so one odd entry never costs the rest. A
price whose tiers are of a kind other than prompt length is left out whole, since part of it would price some calls
wrongly."""

from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Any

from .catalogue_model import Catalogue, ModelFields, Provider, Tier, field_value

_OVER_200K = 200_000


@dataclass(frozen=True)
class Read:
    """What was read, and how many providers and models were left out as unreadable."""

    catalogue: Catalogue
    skipped: int


def parse(data: object) -> Read:
    """Raises ValueError when `data` is not an object of providers, or none of them could be read."""
    entries = _object(data)
    if entries is None:
        raise ValueError("models.dev: expected an object of providers")
    providers: dict[str, Provider] = {}
    skipped = 0
    for pid, entry in entries.items():
        read = _provider(entry)
        if read is None:
            skipped += 1
            continue
        provider, left_out = read
        providers[pid] = provider
        skipped += left_out
    if not providers:
        raise ValueError("models.dev: no provider could be read")
    return Read(Catalogue(providers), skipped)


def _provider(entry: object) -> tuple[Provider, int] | None:
    raw = _object(entry)
    if raw is None:
        return None
    name, api, models = raw.get("name"), raw.get("api"), _object(raw.get("models"))
    if not isinstance(name, str) or not name.strip() or models is None:
        return None
    read = {mid: m for mid, m in ((mid, _model(m)) for mid, m in models.items()) if m is not None}
    return Provider(name, api if isinstance(api, str) and api.startswith("https://") else None, read), \
        len(models) - len(read)


def _model(entry: object) -> ModelFields | None:
    raw = _object(entry)
    if raw is None or not isinstance(raw.get("name"), str) or not isinstance(raw.get("tool_call"), bool):
        return None
    limit = _object(raw.get("limit")) or {}
    structured = raw.get("structured_output")
    model = ModelFields(name=str(raw["name"]).strip()[:200] or None, tool_call=bool(raw["tool_call"]),
                        structured_output=structured if isinstance(structured, bool) else None,
                        context_tokens=_count(limit.get("context")), max_output_tokens=_count(limit.get("output")))
    cost = _object(raw.get("cost"))
    if cost is None:
        return model
    priced = _prices(cost)
    tiers = _tiers(cost)
    if priced is None or tiers is None:
        return model
    return replace(model, **priced, tiers=tiers)


def _prices(cost: dict[str, object]) -> dict[str, Decimal | None] | None:
    """The base prices, None when one present is not a price."""
    out: dict[str, Decimal | None] = {}
    for theirs, ours in (("input", "input_usd_per_mtok"), ("output", "output_usd_per_mtok"),
                         ("cache_read", "cache_read_usd_per_mtok"), ("cache_write", "cache_write_usd_per_mtok")):
        value = cost.get(theirs)
        if value is None:
            out[ours] = None
            continue
        try:
            out[ours] = Decimal(str(field_value("input_usd_per_mtok", value)))
        except ValueError:
            return None
    return out


def _tiers(cost: dict[str, object]) -> tuple[Tier, ...] | None:
    """The prompt-length tiers, ascending; None when any tier is of another kind or does not read."""
    listed: Any = cost.get("tiers")
    entries: list[tuple[int, dict[str, object]]] = []
    if _is_list(listed):
        for item in list[object](listed):
            raw = _object(item)
            kind = _object(raw.get("tier")) if raw is not None else None
            size = _count(kind.get("size")) if kind is not None else None
            if raw is None or kind is None or kind.get("type") != "context" or size is None:
                return None
            entries.append((size, raw))
    elif (over := _object(cost.get("context_over_200k"))) is not None:
        entries.append((_OVER_200K, over))
    tiers: list[Tier] = []
    for size, raw in sorted(entries, key=lambda e: e[0]):
        prices = _prices(raw)
        if prices is None:
            return None
        tiers.append(Tier(size, prices["input_usd_per_mtok"], prices["output_usd_per_mtok"],
                          prices["cache_read_usd_per_mtok"], prices["cache_write_usd_per_mtok"]))
    if len({t.above_prompt_tokens for t in tiers}) != len(tiers):
        return None
    return tuple(tiers)


def _count(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _is_list(value: object) -> bool:
    return isinstance(value, list)


def _object(value: object) -> dict[str, object] | None:
    raw: Any = value
    if not isinstance(value, dict) or not all(isinstance(k, str) for k in raw):
        return None
    return dict[str, object](raw)
