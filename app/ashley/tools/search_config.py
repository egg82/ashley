"""The search sources' tunables, data in `search.json` beside this module: where Photon (places) answers (SearXNG's
address is the deployment's, `Settings.searxng_url`), how long a search may take, how much of each answer she is
shown, and how the house's location is used: its coordinates are rounded to `bias_decimals` before they are sent,
and read again from Home Assistant every `home_ttl_s`."""

import json
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

FILE = Path(__file__).with_name("search.json")


@dataclass(frozen=True)
class SearchConfig:
    photon_url: str
    timeout_s: float
    web_results: int
    snippet_chars: int
    places_fetched: int
    places_results: int
    bias_decimals: int
    home_ttl_s: float


def load() -> SearchConfig:
    """The tunables shipped in `search.json`. Raises ValueError as `parse`."""
    return parse(json.loads(FILE.read_text()))


def parse(data: object) -> SearchConfig:
    """A SearchConfig from JSON already parsed. Raises ValueError when a key is missing or unknown, a URL is not a
    non-empty string, or a number is not positive (counts are integers)."""
    loose: Any = data
    if not isinstance(data, dict):
        raise ValueError("search config is an object")
    raw = dict[object, object](loose)
    names = [f.name for f in fields(SearchConfig)]
    missing = [n for n in names if n not in raw]
    unknown = sorted(str(k) for k in raw if k not in names)
    if missing or unknown:
        raise ValueError(f"search config keys: missing {missing}, unknown {unknown}")
    return SearchConfig(
        photon_url=_url("photon_url", raw["photon_url"]),
        timeout_s=_number("timeout_s", raw["timeout_s"]),
        web_results=_count("web_results", raw["web_results"]),
        snippet_chars=_count("snippet_chars", raw["snippet_chars"]),
        places_fetched=_count("places_fetched", raw["places_fetched"]),
        places_results=_count("places_results", raw["places_results"]),
        bias_decimals=_count("bias_decimals", raw["bias_decimals"]),
        home_ttl_s=_number("home_ttl_s", raw["home_ttl_s"]),
    )


def _url(name: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name}: expected a non-empty string")
    return value.rstrip("/")


def _count(name: str, value: object) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{name}: expected a positive integer")
    return value


def _number(name: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not value > 0:
        raise ValueError(f"{name}: expected a positive number")
    return float(value)
