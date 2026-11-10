"""The bridge client's tunables, data in `herdr.json` beside this module: how long a call may take (`timeout_s`), how
long a start may (`start_timeout_s`, over the bridge's own wait for the new session to report a state), and the most
bytes of an answer read (`response_max_bytes`)."""

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
    size = raw["response_max_bytes"]
    if type(size) is not int or size <= 0:
        raise ValueError("response_max_bytes: expected a positive integer")
    return HerdrConfig(timeout_s=_seconds("timeout_s", raw["timeout_s"]),
                       start_timeout_s=_seconds("start_timeout_s", raw["start_timeout_s"]), response_max_bytes=size)


def _seconds(name: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not value > 0:
        raise ValueError(f"{name}: expected a positive number")
    return float(value)
