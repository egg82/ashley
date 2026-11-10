"""A wake rule piece's body: what she does when Home Assistant wakes her with one event (`decisions.md`, "Home
Assistant wakes her; she decides"). One JSON object of exactly `event` (the event name it answers, the same slug an
automation's wake action sends, `wake_action`), `brief` (her short brief for that turn, at most `MAX_BRIEF`
characters) and `tools` (the names of the tools that turn may use, matched as `ashley.tools.excluding.is_excluded`
matches; empty for none). An empty body is a draft and passes."""

import json
import re
from dataclasses import dataclass
from typing import Any

from .automation_config import object_of

MAX_BRIEF = 1000
EVENT = re.compile(r"[a-z][a-z0-9_]{0,63}")
_TOOL = re.compile(r"[A-Za-z0-9_.\-]{1,128}")
_FIELDS = frozenset(("event", "brief", "tools"))


@dataclass(frozen=True)
class WakeRule:
    event: str
    brief: str
    tools: tuple[str, ...]


def rule_of(body: str) -> WakeRule | None:
    """The rule `body` holds; None when it is empty or not of the shape above."""
    try:
        loaded = object_of(json.loads(body))
    except ValueError:
        return None
    if loaded is None or frozenset(loaded) != _FIELDS:
        return None
    event, brief, tools = loaded["event"], loaded["brief"], _names(loaded["tools"])
    if not isinstance(event, str) or not EVENT.fullmatch(event) or tools is None:
        return None
    if not isinstance(brief, str) or not brief.strip() or len(brief) > MAX_BRIEF:
        return None
    return WakeRule(event, brief, tools)


def well_formed(body: str) -> bool:
    """Whether `body` is empty or a rule of the shape above."""
    return not body.strip() or rule_of(body) is not None


def _names(value: object) -> tuple[str, ...] | None:
    loose: Any = value
    if not isinstance(value, list) or not all(isinstance(n, str) and _TOOL.fullmatch(n) for n in loose):
        return None
    names = tuple(str(n) for n in loose)
    return names if len(set(names)) == len(names) else None
