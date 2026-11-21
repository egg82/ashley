"""The calendar tool's tunables, data in `calendar.json` beside this module: how many days one read covers unless she asks
for more (`days_default`) and at most (`days_max`), and how many events one answer holds."""

import json
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

FILE = Path(__file__).with_name("calendar.json")


@dataclass(frozen=True)
class CalendarConfig:
    days_default: int
    days_max: int
    events_max: int


def load() -> CalendarConfig:
    """The tunables shipped in `calendar.json`. Raises ValueError as `parse`."""
    return parse(json.loads(FILE.read_text()))


def parse(data: object) -> CalendarConfig:
    """A CalendarConfig from JSON already parsed. Raises ValueError when a key is missing or unknown, a value is not a
    positive integer, or the default is over the max."""
    loose: Any = data
    if not isinstance(data, dict):
        raise ValueError("calendar config is an object")
    raw = dict[object, object](loose)
    names = [f.name for f in fields(CalendarConfig)]
    missing = [n for n in names if n not in raw]
    unknown = sorted(str(k) for k in raw if k not in names)
    if missing or unknown:
        raise ValueError(f"calendar config keys: missing {missing}, unknown {unknown}")
    config = CalendarConfig(**{n: _count(n, raw[n]) for n in names})
    if config.days_default > config.days_max:
        raise ValueError("calendar config: days_default is over days_max")
    return config


def _count(name: str, value: object) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{name}: expected a positive integer")
    return value
