"""The bridge client's tunables, data in `herdr.json` beside this module: how long a call may take (`timeout_s`), how
long a start may (`start_timeout_s`, over the bridge's own wait for the new session to report a state), the most
bytes of an answer read (`response_max_bytes`); and for a session shown live on a bench, how many of its last lines are
read (`screen_lines`, 1 to 400) and how soon the page reads it again: while it works (`screen_working_s`), while it does
not (`screen_still_s`), and while the bridge cannot show it (`screen_away_s`)."""

import json
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

FILE = Path(__file__).with_name("herdr.json")


@dataclass(frozen=True)
class HerdrConfig:
    timeout_s: float
    start_timeout_s: float
    response_max_bytes: int
    screen_lines: int
    screen_working_s: float
    screen_still_s: float
    screen_away_s: float


def load() -> HerdrConfig:
    """The tunables shipped in `herdr.json`. Raises ValueError as `parse`."""
    return parse(json.loads(FILE.read_text()))


def parse(data: object) -> HerdrConfig:
    """A HerdrConfig from parsed JSON. Raises ValueError for a missing or unknown key or a value that is not a
    positive number (`response_max_bytes`: a positive integer)."""
    loose: Any = data
    if not isinstance(data, dict):
        raise ValueError("herdr config is an object")
    raw = dict[object, object](loose)
    names = [f.name for f in fields(HerdrConfig)]
    missing = [n for n in names if n not in raw]
    unknown = sorted(str(k) for k in raw if k not in names)
    if missing or unknown:
        raise ValueError(f"herdr config keys: missing {missing}, unknown {unknown}")
    size, lines = raw["response_max_bytes"], raw["screen_lines"]
    if type(size) is not int or size <= 0:
        raise ValueError("response_max_bytes: expected a positive integer")
    if type(lines) is not int or not 1 <= lines <= 400:
        raise ValueError("screen_lines: expected an integer from 1 to 400")
    return HerdrConfig(timeout_s=_seconds("timeout_s", raw["timeout_s"]),
                       start_timeout_s=_seconds("start_timeout_s", raw["start_timeout_s"]), response_max_bytes=size,
                       screen_lines=lines, screen_working_s=_seconds("screen_working_s", raw["screen_working_s"]),
                       screen_still_s=_seconds("screen_still_s", raw["screen_still_s"]),
                       screen_away_s=_seconds("screen_away_s", raw["screen_away_s"]))


def _seconds(name: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not value > 0:
        raise ValueError(f"{name}: expected a positive number")
    return float(value)
