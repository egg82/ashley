"""The catalogue's layers laid over each other, later winning: the snapshot baked into the image, the last good fetch
(which, once there is one, replaces the snapshot whole: it is a newer copy of the same list), and a person's overrides,
each one field of one model. An override stores only what the person changed, so every field it does not name follows
upstream as upstream changes (`decisions.md`, "An override stores only what a person changed").

Pricing a listing (`pricing`) keeps unknown apart from free: no price is `unpriced`; a price of 0 for both input and
output is `listed_zero`, priced as unknown until a person marks the model `free`; every price names the layer it came
from."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from .catalogue_model import PRICE_FIELDS, Catalogue, FieldName, ModelFields, Provider, Tier

Layer = Literal["snapshot", "fetch", "override"]
PriceStatus = Literal["priced", "unpriced", "listed_zero", "free", "local"]


@dataclass(frozen=True)
class Override:
    """One field of one model as a person set it; `set_by` is that person, None once they are gone."""

    provider: str
    model: str
    field: FieldName
    value: object
    set_by: int | None
    set_at: datetime


@dataclass(frozen=True)
class Listing:
    """One model with every layer's say. `default` is upstream's fields (None for a model only a person added) from
    `layer`; `overrides` the fields a person set; `fields` what is in force."""

    provider: str
    model: str
    default: ModelFields | None
    layer: Layer | None
    overrides: Mapping[FieldName, Override]
    fields: ModelFields


@dataclass(frozen=True)
class Pricing:
    """`status` and, where it is priced or free, the `source` layer and the prices in force (`free` carries none)."""

    status: PriceStatus
    source: Layer | Literal["local"] | None
    fields: ModelFields | None


@dataclass(frozen=True)
class Merged:
    providers: Mapping[str, Provider]
    listings: Mapping[tuple[str, str], Listing]


UNPRICED = Pricing("unpriced", None, None)
LOCAL = Pricing("local", "local", None)


def upstream(snapshot: Catalogue | None, fetched: Catalogue | None) -> tuple[Catalogue, Layer | None]:
    """The upstream layer in force: the fetch when there is one, else the snapshot, else nothing."""
    if fetched is not None:
        return fetched, "fetch"
    if snapshot is not None:
        return snapshot, "snapshot"
    return Catalogue({}), None


def merged(catalogue: Catalogue, layer: Layer | None, overrides: Iterable[Override]) -> Merged:
    """Every upstream model and every model a person named, with the person's fields over upstream's. A provider only
    a person named is listed under its own id as its name."""
    by_model: dict[tuple[str, str], dict[FieldName, Override]] = {}
    for o in overrides:
        by_model.setdefault((o.provider, o.model), {})[o.field] = o
    listings: dict[tuple[str, str], Listing] = {}
    for pid, provider in catalogue.providers.items():
        for mid, fields in provider.models.items():
            listings[(pid, mid)] = _listing(pid, mid, fields, layer, by_model.pop((pid, mid), {}))
    for (pid, mid), set_fields in by_model.items():
        listings[(pid, mid)] = _listing(pid, mid, None, None, set_fields)
    providers = dict(catalogue.providers)
    for pid, _ in listings:
        providers.setdefault(pid, Provider(pid, None, {}))
    return Merged(providers, listings)


def _listing(pid: str, mid: str, default: ModelFields | None, layer: Layer | None,
             set_fields: Mapping[FieldName, Override]) -> Listing:
    fields = default or ModelFields()
    for name, o in set_fields.items():
        fields = fields.with_value(name, o.value)
    return Listing(pid, mid, default, layer if default is not None else None, set_fields, fields)


def delta(default: ModelFields | None, put: Mapping[FieldName, object],
          reset: Iterable[FieldName]) -> tuple[dict[FieldName, object], set[FieldName]]:
    """What a person's change stores and deletes: each field of `put` whose value differs from upstream's `default`
    (None for a model only a person lists) is stored, one equal to it is deleted, and so is each of `reset`. A person's
    only flags (`free`, `hidden`) default to false, so setting one false deletes it."""
    stored: dict[FieldName, object] = {}
    deleted = set(reset)
    for field, value in put.items():
        upstream_value = (default or ModelFields()).get(field)
        if upstream_value is None and field in ("free", "hidden"):
            upstream_value = False
        if value == upstream_value:
            deleted.add(field)
        else:
            stored[field] = value
            deleted.discard(field)
    return stored, deleted


def pricing(listing: Listing | None) -> Pricing:
    if listing is None:
        return UNPRICED
    fields = listing.fields
    if fields.free:
        return Pricing("free", "override", None)
    if fields.input_usd_per_mtok is None and fields.output_usd_per_mtok is None:
        return UNPRICED
    source: Layer | None = "override" if PRICE_FIELDS & set(listing.overrides) else listing.layer
    status: PriceStatus = "listed_zero" if _all_zero(fields) else "priced"
    return Pricing(status, source, fields)


def _all_zero(fields: ModelFields) -> bool:
    rates = [fields.input_usd_per_mtok, fields.output_usd_per_mtok, fields.cache_read_usd_per_mtok,
             fields.cache_write_usd_per_mtok]
    for tier in fields.tiers:
        rates += [tier.input_usd_per_mtok, tier.output_usd_per_mtok, tier.cache_read_usd_per_mtok,
                  tier.cache_write_usd_per_mtok]
    return all(r is None or r == 0 for r in rates)


def rates_for(fields: ModelFields, prompt_tokens: int) -> ModelFields | Tier:
    """The prices a prompt of `prompt_tokens` pays: the highest tier it is longer than, else the base."""
    found: ModelFields | Tier = fields
    for tier in fields.tiers:
        if prompt_tokens > tier.above_prompt_tokens:
            found = tier
    return found
