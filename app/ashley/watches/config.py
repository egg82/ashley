"""The watches tunables, data in `watches.json` beside this module: `tick_s` between job ticks, `batch` watches checked
per tick, `read_timeout_s` for one kind's read, `fail_after` failures in a row before a watch pauses, `retry_s` between
checks of a paused one, `wake_max_age_s` a wake stays worth telling, `keep_s` an ended watch is kept, `max_live`
watches per person, `max_items` items and `max_value_chars` per tracked text, `max_alternatives` and `max_predicates`
of a condition, and `kinds`: per kind its `interval_s`, default and largest `hours`, `handoff_hours`, `track`, default
`when` and `handoff_until`, and `outside`: whether what the kind reads can carry text written outside the household.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..criteria import condition
from ..criteria.condition import Condition

FILE = Path(__file__).with_name("watches.json")
_NUMBERS = ("tick_s", "batch", "read_timeout_s", "fail_after", "retry_s", "wake_max_age_s", "keep_s", "max_live",
            "max_items", "max_value_chars", "max_alternatives", "max_predicates")
_KIND_NUMBERS = ("interval_s", "hours", "max_hours", "handoff_hours")
_KIND_KEYS = {*_KIND_NUMBERS, "track", "when", "handoff_until", "outside"}


@dataclass(frozen=True)
class KindConfig:
    interval_s: float
    hours: float
    max_hours: float
    handoff_hours: float
    track: tuple[str, ...]
    when: Condition
    handoff_until: Condition
    outside: bool


@dataclass(frozen=True)
class WatchesConfig:
    tick_s: float
    batch: int
    read_timeout_s: float
    fail_after: int
    retry_s: float
    wake_max_age_s: float
    keep_s: float
    max_live: int
    max_items: int
    max_value_chars: int
    max_alternatives: int
    max_predicates: int
    kinds: Mapping[str, KindConfig]


def load() -> WatchesConfig:
    """The tunables shipped in `watches.json`. Raises ValueError when one is missing, unknown or not positive, or a
    kind's conditions read an untracked field or exceed the limits."""
    raw = json.loads(FILE.read_text())
    if set(raw) != {*_NUMBERS, "kinds"}:
        raise ValueError(f"watches.json has exactly {sorted({*_NUMBERS, 'kinds'})}")
    if min(raw[n] for n in _NUMBERS) <= 0:
        raise ValueError("watches tunables must be positive")
    kinds = {name: _kind(body, raw) for name, body in raw["kinds"].items()}
    return WatchesConfig(float(raw["tick_s"]), int(raw["batch"]), float(raw["read_timeout_s"]), int(raw["fail_after"]),
                         float(raw["retry_s"]), float(raw["wake_max_age_s"]), float(raw["keep_s"]),
                         int(raw["max_live"]), int(raw["max_items"]), int(raw["max_value_chars"]),
                         int(raw["max_alternatives"]), int(raw["max_predicates"]), kinds)


def _kind(body: Any, raw: Any) -> KindConfig:
    if set(body) != _KIND_KEYS:
        raise ValueError(f"a kind in watches.json has exactly {sorted(_KIND_KEYS)}")
    numbers = {n: float(body[n]) for n in _KIND_NUMBERS}
    track = tuple(str(t) for t in body["track"])
    when, until = condition.from_json(body["when"]), condition.from_json(body["handoff_until"])
    for c in (when, until):
        condition.validate(c, track, int(raw["max_alternatives"]), int(raw["max_predicates"]))
    if min(numbers.values()) <= 0 or numbers["hours"] > numbers["max_hours"] or not 1 <= len(track) <= 8:
        raise ValueError("a kind has positive numbers, hours within max_hours and 1 to 8 tracked fields")
    return KindConfig(numbers["interval_s"], numbers["hours"], numbers["max_hours"], numbers["handoff_hours"], track,
                      when, until, _flag(body["outside"]))


def _flag(value: Any) -> bool:
    if not isinstance(value, bool):
        raise ValueError("a kind's outside is true or false")
    return value


CONFIG = load()
