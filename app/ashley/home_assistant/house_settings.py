"""The adapter's tunables, data in `house.json` beside this module: `timeout_s` for each request and the largest
WebSocket message read (`socket_max_bytes`, since a registry of a big house is megabytes)."""

import json
from dataclasses import dataclass
from pathlib import Path

from .ha_json import obj

FILE = Path(__file__).with_name("house.json")
_KEYS = {"timeout_s", "socket_max_bytes"}


@dataclass(frozen=True)
class HouseSettings:
    timeout_s: float
    socket_max_bytes: int


def load() -> HouseSettings:
    """The tunables shipped in `house.json`. Raises ValueError as `parse`."""
    return parse(json.loads(FILE.read_text()))


def parse(raw: object) -> HouseSettings:
    """HouseSettings from JSON already parsed. Raises ValueError unless the keys are exactly `timeout_s` and
    `socket_max_bytes`, both numbers above 0."""
    top = obj(raw)
    if not isinstance(raw, dict) or set(top) != _KEYS:
        raise ValueError("house.json has exactly timeout_s and socket_max_bytes")
    timeout, size = top["timeout_s"], top["socket_max_bytes"]
    if not isinstance(timeout, int | float) or not isinstance(size, int):
        raise ValueError("house.json: timeout_s is a number and socket_max_bytes a whole number")
    settings = HouseSettings(float(timeout), size)
    if settings.timeout_s <= 0 or settings.socket_max_bytes <= 0:
        raise ValueError("house.json: timeout_s and socket_max_bytes above 0")
    return settings
