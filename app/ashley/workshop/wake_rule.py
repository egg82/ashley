"""A wake rule piece's body: what she does when Home Assistant wakes her with one event (`decisions.md`, "Home
Assistant wakes her; she decides"). One JSON object of exactly `event` (the event name it answers, the same slug an
automation's wake action sends, `wake_action`), `brief` (her short brief for that turn, at most `MAX_BRIEF`
characters) and `tools` (the names of the tools that turn may use, matched as `ashley.tools.excluding.is_excluded`
matches; empty for none), and optionally `greets` (a bool, false when absent: whether the wake is a greeting, whose
turn `Initiative` scores and rolls; any other wake's reply goes out on her `says` alone), `who` (a `person.*` entity
id) and `what` (a slug): set, the rule answers only a wake whose own `who` or `what` (`ashley.senses.wakes.Wake`) is
exactly that; absent, any. `speaker` (a `media_player.*` entity id) names the household's Home Assistant media player
the turn is said on instead of the phone; whether it is one of the household's is read when a wake runs
(`ashley.channels.wake.speaker`), since this check is pure. `device` (a device id) names the household's paired kiosk
the turn is announced on instead (`ashley.channels.wake.reminder_device`), likewise read when a wake runs; a rule
naming both a speaker and a device is no rule. An empty body is a draft and passes."""

import json
import re
from dataclasses import dataclass
from typing import Any

from .automation_config import object_of

MAX_BRIEF = 1000
EVENT = re.compile(r"[a-z][a-z0-9_]{0,63}")
_TOOL = re.compile(r"[A-Za-z0-9_.\-]{1,128}")
_PERSON = re.compile(r"person\.[a-z0-9_]+")
_SPEAKER = re.compile(r"media_player\.[a-z0-9_]+")
_FIELDS = frozenset(("event", "brief", "tools"))
_OPTIONAL = frozenset(("greets", "who", "what", "speaker", "device"))


@dataclass(frozen=True)
class WakeRule:
    event: str
    brief: str
    tools: tuple[str, ...]
    greets: bool = False
    who: str | None = None
    what: str | None = None
    speaker: str | None = None
    device: int | None = None

    @property
    def specificity(self) -> int:
        """How many of `who` and `what` it sets; of the rules answering one wake, only the most specific may run."""
        return (self.who is not None) + (self.what is not None)

    def answers(self, event: str, who: str | None, what: str | None) -> bool:
        """Whether it answers a wake of `event` about `who` and `what`."""
        return (self.event == event and (self.who is None or self.who == who)
                and (self.what is None or self.what == what))


def rule_of(body: str) -> WakeRule | None:
    """The rule `body` holds; None when it is empty or not of the shape above."""
    try:
        loaded = object_of(json.loads(body))
    except ValueError:
        return None
    if loaded is None or not _FIELDS <= frozenset(loaded) <= _FIELDS | _OPTIONAL:
        return None
    greets, (who_ok, who), (what_ok, what) = (loaded.get("greets", False), _match(loaded, "who", _PERSON),
                                                _match(loaded, "what", EVENT))
    speaker_ok, speaker = _match(loaded, "speaker", _SPEAKER)
    device = loaded.get("device")
    if not isinstance(greets, bool) or not who_ok or not what_ok or not speaker_ok:
        return None
    if "device" in loaded and (type(device) is not int or device < 1 or speaker is not None):
        return None
    event, brief, tools = loaded["event"], loaded["brief"], _names(loaded["tools"])
    if not isinstance(event, str) or not EVENT.fullmatch(event) or tools is None:
        return None
    if not isinstance(brief, str) or not brief.strip() or len(brief) > MAX_BRIEF:
        return None
    return WakeRule(event, brief, tools, greets, who, what, speaker, device)


def well_formed(body: str) -> bool:
    """Whether `body` is empty or a rule of the shape above."""
    return not body.strip() or rule_of(body) is not None


def _match(loaded: dict[str, Any], key: str, shape: re.Pattern[str]) -> tuple[bool, str | None]:
    """Whether the match field `key` is absent or of `shape`, and its value (None when absent)."""
    if key not in loaded:
        return True, None
    value: object = loaded[key]
    return (True, value) if isinstance(value, str) and shape.fullmatch(value) else (False, None)


def _names(value: object) -> tuple[str, ...] | None:
    loose: Any = value
    if not isinstance(value, list) or not all(isinstance(n, str) and _TOOL.fullmatch(n) for n in loose):
        return None
    names = tuple(str(n) for n in loose)
    return names if len(set(names)) == len(names) else None
