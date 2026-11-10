"""What the spend page knows about each provider besides the ledger: `providers.json` (its label, whether it costs
money, why no balance can be read for it, and the page that says so) and `budgets.json` (the household's optional
monthly budget per provider, in USD, shipped empty). Both are data beside `prices.json`."""

import json
import math
from dataclasses import dataclass
from importlib import resources
from typing import Any, Literal


@dataclass(frozen=True)
class ProviderInfo:
    """`why_unknown` is only for a paid provider with no way to read its balance wired; `source` is the documentation
    page behind that, or behind the read where one exists."""

    label: str
    kind: Literal["paid", "local"]
    why_unknown: str | None
    source: str | None


@dataclass(frozen=True)
class Catalog:
    providers: dict[str, ProviderInfo]
    monthly_usd: dict[str, float]


def load() -> Catalog:
    """The catalog shipped beside this module (`parse`)."""
    read = resources.files("ashley.inference")
    return parse(json.loads(read.joinpath("providers.json").read_text()), json.loads(read.joinpath("budgets.json").read_text()))


def parse(providers: object, budgets: object) -> Catalog:
    """`providers`: `{"<provider>": {"label": str, "kind": "paid" | "local", "why_unknown"?: str, "source"?: url}}`;
    `budgets`: `{"monthly_usd": {"<provider>": number above 0}}`, naming only providers in `providers`. Raises
    ValueError naming what is wrong."""
    known = {name: _info(name, entry) for name, entry in _object("providers", providers).items()}
    asked = _object("budgets.monthly_usd", _object("budgets", budgets).get("monthly_usd"))
    return Catalog(known, {name: _budget(name, known, value) for name, value in asked.items()})


def _info(name: str, entry: object) -> ProviderInfo:
    fields = _object(name, entry)
    if set(fields) - {"label", "kind", "why_unknown", "source"} or not {"label", "kind"} <= set(fields):
        raise ValueError(f"{name}: expected label, kind and optionally why_unknown and source")
    kind = fields["kind"]
    if kind not in ("paid", "local"):
        raise ValueError(f"{name}.kind: expected paid or local")
    return ProviderInfo(_text(f"{name}.label", fields["label"]), kind, _maybe(f"{name}.why_unknown", fields),
                        _maybe(f"{name}.source", fields))


def _budget(name: str, known: dict[str, ProviderInfo], value: object) -> float:
    if name not in known or known[name].kind != "paid":
        raise ValueError(f"budgets.monthly_usd.{name}: not a paid provider in providers.json")
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value) or value <= 0:
        raise ValueError(f"budgets.monthly_usd.{name}: expected a number above 0")
    return float(value)


def _maybe(where: str, fields: dict[str, object]) -> str | None:
    key = where.rsplit(".", 1)[1]
    return _text(where, fields[key]) if key in fields else None


def _text(where: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{where}: expected a non-empty string")
    return value


def _object(where: str, value: object) -> dict[str, object]:
    raw: Any = value
    if not hasattr(raw, "keys") or not all(type(key) is str for key in raw.keys()):
        raise ValueError(f"{where}: expected an object")
    return dict[str, object](raw)
