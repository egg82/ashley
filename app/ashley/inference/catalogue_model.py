"""The model catalogue's records: what is known of one model (`ModelFields`), the providers that list them
(`Catalogue`), and the JSON form both are stored in. A catalogue is one layer's view; `catalogue_merge` lays the layers
over each other. Prices are USD per million tokens, held as exact decimals; a field that is None is not known."""

from collections.abc import Mapping
from dataclasses import dataclass, fields, replace
from decimal import Decimal
from typing import Any, Literal, get_args

FieldName = Literal["name", "tool_call", "structured_output", "context_tokens", "max_output_tokens",
                    "input_usd_per_mtok", "output_usd_per_mtok", "cache_read_usd_per_mtok", "cache_write_usd_per_mtok",
                    "free", "hidden"]
"""The fields a person may override. `free` (a person says the model costs nothing, which no upstream layer can say)
and `hidden` (left out of what the page offers) are a person's only."""

FIELD_NAMES: tuple[FieldName, ...] = get_args(FieldName)
PRICE_FIELDS: frozenset[FieldName] = frozenset({"input_usd_per_mtok", "output_usd_per_mtok",
                                                "cache_read_usd_per_mtok", "cache_write_usd_per_mtok"})
_BOOLS = frozenset({"tool_call", "structured_output", "free", "hidden"})
_COUNTS = frozenset({"context_tokens", "max_output_tokens"})


@dataclass(frozen=True)
class Tier:
    """The prices for a prompt longer than `above_prompt_tokens` (input, cache-read and cache-write tokens together)."""

    above_prompt_tokens: int
    input_usd_per_mtok: Decimal | None
    output_usd_per_mtok: Decimal | None
    cache_read_usd_per_mtok: Decimal | None
    cache_write_usd_per_mtok: Decimal | None


@dataclass(frozen=True)
class ModelFields:
    """One model as one layer knows it. `tiers` ascend by `above_prompt_tokens` and apply over the base prices; they
    come only from upstream, and a person's price on any price field replaces them (the model is then priced flat)."""

    name: str | None = None
    tool_call: bool | None = None
    structured_output: bool | None = None
    context_tokens: int | None = None
    max_output_tokens: int | None = None
    input_usd_per_mtok: Decimal | None = None
    output_usd_per_mtok: Decimal | None = None
    cache_read_usd_per_mtok: Decimal | None = None
    cache_write_usd_per_mtok: Decimal | None = None
    free: bool | None = None
    hidden: bool | None = None
    tiers: tuple[Tier, ...] = ()

    def get(self, field: FieldName) -> object:
        value: object = getattr(self, field)
        return value

    def with_value(self, field: FieldName, value: object) -> "ModelFields":
        """These fields with `field` set to `value` (checked by `field_value`); a price drops the tiers."""
        changed = replace(self, **{field: value})
        return replace(changed, tiers=()) if field in PRICE_FIELDS else changed


@dataclass(frozen=True)
class Provider:
    """A provider as one layer lists it: its display name, its OpenAI-compatible base URL where it has one, its
    models by id."""

    name: str
    api: str | None
    models: Mapping[str, ModelFields]


@dataclass(frozen=True)
class Catalogue:
    providers: Mapping[str, Provider]

    def model_count(self) -> int:
        return sum(len(p.models) for p in self.providers.values())


EMPTY = Catalogue({})


def field_value(field: FieldName, value: object) -> object:
    """`value` checked for `field` and in its held type: a price is a decimal of 0 or more (given as a JSON number or
    decimal text), a count a whole number above 0, a flag a boolean, a name non-empty text of at most 200 characters.
    Raises ValueError naming the field."""
    if field in PRICE_FIELDS:
        return _price(field, value)
    if field in _BOOLS:
        if not isinstance(value, bool):
            raise ValueError(f"{field}: expected true or false")
        return value
    if field in _COUNTS:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{field}: expected a whole number above 0")
        return value
    if not isinstance(value, str) or not value.strip() or len(value) > 200:
        raise ValueError(f"{field}: expected text of 1 to 200 characters")
    return value


def _price(field: str, value: object) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, int | float | str | Decimal):
        raise ValueError(f"{field}: expected a number")
    try:
        price = Decimal(repr(value)) if isinstance(value, float) else Decimal(value)
    except ArithmeticError:
        raise ValueError(f"{field}: expected a number") from None
    if not price.is_finite() or price < 0:
        raise ValueError(f"{field}: expected a finite number of 0 or more")
    return price


def to_json(value: object) -> object:
    """A held field value as JSON: a decimal as its text, everything else as itself."""
    return str(value) if isinstance(value, Decimal) else value


def fields_to_json(model: ModelFields) -> dict[str, object]:
    """The known fields of `model` (None left out), tiers as a list of objects."""
    out: dict[str, object] = {f: to_json(model.get(f)) for f in FIELD_NAMES if model.get(f) is not None}
    if model.tiers:
        out["tiers"] = [{f.name: to_json(getattr(t, f.name)) for f in fields(Tier) if getattr(t, f.name) is not None}
                        for t in model.tiers]
    return out


def fields_from_json(data: object) -> ModelFields:
    """`fields_to_json`'s output read back. Raises ValueError for an unknown field or a value its field refuses."""
    raw = _object(data)
    unknown = set(raw) - set(FIELD_NAMES) - {"tiers"}
    if unknown:
        raise ValueError(f"unknown model fields: {', '.join(sorted(unknown))}")
    model = ModelFields()
    for name in FIELD_NAMES:
        if name in raw:
            model = replace(model, **{name: field_value(name, raw[name])})
    return replace(model, tiers=tiers_from_json(raw.get("tiers", [])))


def tiers_from_json(data: object) -> tuple[Tier, ...]:
    loose: Any = data
    if not isinstance(data, list):
        raise ValueError("tiers: expected a list")
    tiers = tuple(_tier(t) for t in list[object](loose))
    bounds = [t.above_prompt_tokens for t in tiers]
    if bounds != sorted(set(bounds)):
        raise ValueError("tiers: expected ascending, distinct above_prompt_tokens")
    return tiers


def _tier(data: object) -> Tier:
    raw = _object(data)
    above = raw.get("above_prompt_tokens")
    if isinstance(above, bool) or not isinstance(above, int) or above <= 0:
        raise ValueError("tiers: above_prompt_tokens is a whole number above 0")
    prices = {f: None if raw.get(f) is None else _price(f, raw[f]) for f in sorted(PRICE_FIELDS)}
    return Tier(above, **prices)


def catalogue_to_json(catalogue: Catalogue) -> dict[str, object]:
    return {pid: {"name": p.name, "api": p.api, "models": {mid: fields_to_json(m) for mid, m in p.models.items()}}
            for pid, p in catalogue.providers.items()}


def catalogue_from_json(data: object) -> Catalogue:
    """`catalogue_to_json`'s output read back. Raises ValueError when any part of it is not that shape."""
    providers: dict[str, Provider] = {}
    for pid, entry in _object(data).items():
        raw = _object(entry)
        name, api = raw.get("name"), raw.get("api")
        if not isinstance(name, str) or not (api is None or isinstance(api, str)):
            raise ValueError(f"{pid}: expected a name and an api of text or null")
        providers[pid] = Provider(name, api, {mid: fields_from_json(m) for mid, m in _object(raw.get("models")).items()})
    return Catalogue(providers)


def _object(value: object) -> dict[str, object]:
    raw: Any = value
    if not isinstance(value, dict) or not all(isinstance(k, str) for k in raw):
        raise ValueError("expected an object")
    return dict[str, object](raw)
