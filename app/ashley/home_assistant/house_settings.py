"""The adapter's tunables, data in `house.json` beside this module: `timeout_s` for each request, the largest
WebSocket message read (`socket_max_bytes`, since a registry of a big house is megabytes), and how long a written
automation is waited for as a thing (`entity_tries` reads `entity_wait_s` apart), since the house reloads it after
answering the write."""

import json
from dataclasses import dataclass
from pathlib import Path

from .ha_json import obj

FILE = Path(__file__).with_name("house.json")
_KEYS = {"timeout_s", "socket_max_bytes", "entity_tries", "entity_wait_s"}


@dataclass(frozen=True)
class HouseSettings:
    timeout_s: float
    socket_max_bytes: int
    entity_tries: int
    entity_wait_s: float


def load() -> HouseSettings:
    """The tunables shipped in `house.json`. Raises ValueError as `parse`."""
    return parse(json.loads(FILE.read_text()))


def parse(raw: object) -> HouseSettings:
    """HouseSettings from JSON already parsed. Raises ValueError unless the keys are exactly `timeout_s`,
    `socket_max_bytes`, `entity_tries` (whole numbers, at least 1) and `entity_wait_s` (0 or more)."""
    top = obj(raw)
    if not isinstance(raw, dict) or set(top) != _KEYS:
        raise ValueError("house.json has exactly timeout_s, socket_max_bytes, entity_tries and entity_wait_s")
    timeout, size, tries, wait = top["timeout_s"], top["socket_max_bytes"], top["entity_tries"], top["entity_wait_s"]
    if not isinstance(timeout, int | float) or not isinstance(wait, int | float) or not isinstance(size, int) \
            or not isinstance(tries, int):
        raise ValueError("house.json: timeout_s and entity_wait_s are numbers, socket_max_bytes and entity_tries whole")
    settings = HouseSettings(float(timeout), size, tries, float(wait))
    if settings.timeout_s <= 0 or settings.socket_max_bytes <= 0 or settings.entity_tries < 1 \
            or settings.entity_wait_s < 0:
        raise ValueError("house.json: timeout_s and socket_max_bytes above 0, entity_tries 1 or more, entity_wait_s 0 or "
                         "more")
    return settings
