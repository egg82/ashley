"""The model catalogue's tunables, `catalogue.json` beside this module: where the list is fetched from and how often,
and which catalogue provider each route's provider name is listed under where the two differ. The providers whose
calls bill nobody are those `providers.json` marks `local` (`spend_catalog`)."""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import spend_catalog

FILE = Path(__file__).with_name("catalogue.json")


@dataclass(frozen=True)
class CatalogueConfig:
    url: str
    refresh_s: float
    retry_s: float
    timeout_s: float
    providers: Mapping[str, str]
    local: frozenset[str]

    def listed_as(self, provider: str) -> str:
        """The catalogue provider a route's `provider` is listed under: its mapping, else its own name."""
        return self.providers.get(provider, provider)


def load() -> CatalogueConfig:
    local = frozenset(name for name, info in spend_catalog.load().providers.items() if info.kind == "local")
    return parse(json.loads(FILE.read_text()), local)


def parse(data: object, local: frozenset[str] = frozenset()) -> CatalogueConfig:
    """`local` names the providers whose calls cost 0. Raises ValueError for a missing or unknown key, a url that is not
    https, a duration that is not above 0, or a provider name that is not non-empty text."""
    raw = _object(data) or {}
    if set(raw) != {"url", "refresh_s", "retry_s", "timeout_s", "providers"}:
        raise ValueError("catalogue config keys are url, refresh_s, retry_s, timeout_s, providers")
    url = raw["url"]
    if not isinstance(url, str) or not url.startswith("https://"):
        raise ValueError("url is an https URL")
    mapping = _object(raw["providers"])
    if mapping is None or not all(_name(k) and _name(v) for k, v in mapping.items()):
        raise ValueError("providers maps provider names to provider names")
    return CatalogueConfig(url, _seconds(raw["refresh_s"], "refresh_s"), _seconds(raw["retry_s"], "retry_s"),
                           _seconds(raw["timeout_s"], "timeout_s"),
                           {k: str(v) for k, v in mapping.items()}, local)


def _object(value: object) -> dict[str, object] | None:
    raw: Any = value
    if not isinstance(value, dict) or not all(isinstance(k, str) for k in raw):
        return None
    return dict[str, object](raw)


def _name(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _seconds(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
        raise ValueError(f"{name} is a number above 0")
    return float(value)
