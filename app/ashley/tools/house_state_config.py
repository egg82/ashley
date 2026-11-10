"""`house_state`'s tunables, data in `house_state.json` beside this module: the most characters one answer may hold,
how many of a kind are named one by one in a summary before they are counted instead, how many different states a
summary counts before it counts kinds instead, which attributes a summary names beside a state, and which domains
carry text strangers write in their attributes (a calendar's current event), so an answer showing one is outside text."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

FILE = Path(__file__).with_name("house_state.json")
_COUNTS = ("max_chars", "list_at_most", "tally_at_most")


@dataclass(frozen=True)
class HouseStateConfig:
    max_chars: int
    list_at_most: int
    tally_at_most: int
    summary_attributes: tuple[str, ...]
    outside_domains: tuple[str, ...]


def load() -> HouseStateConfig:
    """The tunables shipped in `house_state.json`. Raises ValueError as `parse`."""
    return parse(json.loads(FILE.read_text()))


def parse(data: object) -> HouseStateConfig:
    """A HouseStateConfig from JSON already parsed. Raises ValueError when a key is missing or unknown, a count is not a
    positive integer, or `summary_attributes` or `outside_domains` is not a list of non-empty strings."""
    loose: Any = data
    if not isinstance(data, dict):
        raise ValueError("house state config is an object")
    raw = dict[object, object](loose)
    names = [*_COUNTS, "summary_attributes", "outside_domains"]
    missing = [n for n in names if n not in raw]
    unknown = sorted(str(k) for k in raw if k not in names)
    if missing or unknown:
        raise ValueError(f"house state config keys: missing {missing}, unknown {unknown}")
    counts = {n: _count(n, raw[n]) for n in _COUNTS}
    return HouseStateConfig(summary_attributes=_names("summary_attributes", raw["summary_attributes"]),
                            outside_domains=_names("outside_domains", raw["outside_domains"]), **counts)


def _count(name: str, value: object) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{name}: expected a positive integer")
    return value


def _names(key: str, value: object) -> tuple[str, ...]:
    loose: Any = value
    items: list[object] = list(loose) if isinstance(value, list) else []
    names = tuple(v for v in items if isinstance(v, str) and v.strip())
    if not isinstance(value, list) or len(names) != len(items):
        raise ValueError(f"{key}: expected a list of non-empty strings")
    return names
