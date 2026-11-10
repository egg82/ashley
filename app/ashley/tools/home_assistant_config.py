"""Which of the house's actions she is never offered (`excluded`), data in `home_assistant.json` beside this module (each
entry an action, `domain.name`), and her own guidance for using the house's tools, `home_assistant.md` beside it. What
is the household's own (which reads are its lists or a trusted service's, which scripts only look something up, which
things are always asked about) is a setting of its Home Assistant connection (`home_assistant.house_values`)."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

FILE = Path(__file__).with_name("home_assistant.json")
GUIDANCE = Path(__file__).with_name("home_assistant.md")


@dataclass(frozen=True)
class HomeAssistantConfig:
    excluded: tuple[str, ...]
    guidance: str


def load() -> HomeAssistantConfig:
    """The lists shipped in `home_assistant.json`. Raises ValueError as `parse`."""
    return parse(json.loads(FILE.read_text()), GUIDANCE.read_text().strip())


def parse(data: object, guidance: str = "") -> HomeAssistantConfig:
    """A HomeAssistantConfig from JSON already parsed. Raises ValueError when the only key is not `excluded`, a list of
    non-empty strings; `guidance` is her own text for the house's tools."""
    loose: Any = data
    if not isinstance(data, dict):
        raise ValueError("home assistant config is an object")
    raw = dict[object, object](loose)
    if set(raw) != {"excluded"}:
        raise ValueError("home assistant config has the key excluded, and no other")
    return HomeAssistantConfig(_names(loose["excluded"]), guidance)


def _names(value: object) -> tuple[str, ...]:
    loose: Any = value
    if not isinstance(value, list):
        raise ValueError("excluded: expected a list of non-empty strings")
    items: list[object] = list(loose)
    names = [e for e in items if isinstance(e, str) and e.strip()]
    if len(names) != len(items):
        raise ValueError("excluded: expected a list of non-empty strings")
    return tuple(names)
