"""The caps on what her house tools return, data in `house_look.json` beside this module: how long a catalogue is kept
(`catalogue_ttl_s`), how long a change proposed to a person can still be confirmed (`proposal_ttl_s`), the most characters one answer holds (`max_chars`), the most the line of the house's devices in her instructions holds (`devices_chars`), how many records `house_find` names before
it counts instead (`find_default`), how far back and for how many things `house_history` reads (`history_max_hours`,
`history_default_hours`, `history_max_things`; `logbook_max_things` for the logbook), and the most readings per thing
(`readings_per_thing`) and logbook entries (`entries_max`) one answer shows."""

import json
from dataclasses import dataclass
from pathlib import Path

from ..home_assistant.ha_json import obj

FILE = Path(__file__).with_name("house_look.json")
_KEYS = ("catalogue_ttl_s", "proposal_ttl_s", "max_chars", "devices_chars", "find_default", "history_max_hours", "history_default_hours",
         "history_max_things", "logbook_max_things", "readings_per_thing", "entries_max")


@dataclass(frozen=True)
class HouseLookConfig:
    catalogue_ttl_s: float
    proposal_ttl_s: float
    max_chars: int
    devices_chars: int
    find_default: int
    history_max_hours: int
    history_default_hours: int
    history_max_things: int
    logbook_max_things: int
    readings_per_thing: int
    entries_max: int


def load() -> HouseLookConfig:
    """The caps shipped in `house_look.json`. Raises ValueError as `parse`."""
    return parse(json.loads(FILE.read_text()))


def parse(raw: object) -> HouseLookConfig:
    """HouseLookConfig from JSON already parsed. Raises ValueError unless the keys are exactly the eleven and each is a
    positive number (the counts integers)."""
    top = obj(raw)
    if not isinstance(raw, dict) or set(top) != set(_KEYS):
        raise ValueError(f"house_look.json has exactly {', '.join(_KEYS)}")
    for key in _KEYS:
        value = top[key]
        seconds = key.endswith("_ttl_s")
        if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0 or (not seconds and not isinstance(value, int)):
            raise ValueError(f"{key}: expected a positive number" if seconds else f"{key}: expected a positive integer")
    return HouseLookConfig(float(_number(top["catalogue_ttl_s"])), float(_number(top["proposal_ttl_s"])),
                           *(int(_number(top[k])) for k in _KEYS[2:]))


def _number(value: object) -> int | float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError("expected a number")
    return value
