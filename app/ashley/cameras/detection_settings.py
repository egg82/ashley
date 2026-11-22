"""What a camera's detector events do, as data (`detection.json`): `show_feed_on` the detector classes that put the
camera's live feed on the visible screens, `min_gap_s` the least time between two such feeds for one camera (counted
between the events' own times), `keep_s` how long a recorded detection is kept, `failure_lookback_s` how far back a printer's failed print is still told when the passes resume after a gap (the record keeps one told twice from acting twice), and `tick_s` between the passes that
follow the cameras again, so a camera named or dropped is followed or let go within it. `speak_on` the classes she says
what happened on, from a look at what the detector captured (`ashley.channels.wake.detection_turn`), and `speak_in_quiet_on` the classes she says even when every person of the household is within their own quiet hours (a doorbell at night is fine; any other class is held), and `look_wait_s` how long
after the event she waits for that recording to appear before she speaks without it. `look_now_on` the classes whose picture is
the camera's own view as she speaks, not a recording: a printer's failure, which leaves none, is told with its snapshot."""

import json
from dataclasses import dataclass
from pathlib import Path

FILE = Path(__file__).with_name("detection.json")
_LISTS = ("show_feed_on", "speak_on", "look_now_on", "speak_in_quiet_on")
_NUMBERS = ("look_wait_s", "min_gap_s", "keep_s", "tick_s", "failure_lookback_s")
_KEYS = _LISTS + _NUMBERS


@dataclass(frozen=True)
class DetectionSettings:
    show_feed_on: frozenset[str]
    min_gap_s: float
    keep_s: float
    tick_s: float
    speak_on: frozenset[str] = frozenset()
    look_wait_s: float = 60
    look_now_on: frozenset[str] = frozenset()
    failure_lookback_s: float = 1800
    speak_in_quiet_on: frozenset[str] = frozenset()


def load() -> DetectionSettings:
    """The tunables in `detection.json`. Raises ValueError unless it has exactly its keys: four lists of classes (non-empty
    strings, which may be none) and five numbers above 0."""
    raw = json.loads(FILE.read_text())
    if set(raw) != set(_KEYS):
        raise ValueError(f"detection.json has exactly {', '.join(_KEYS)}")
    for key in _LISTS:
        if not isinstance(raw[key], list) or not all(isinstance(c, str) and c for c in raw[key]):
            raise ValueError(f"detection.json's {key} is a list of detector classes")
    numbers = [raw[k] for k in _NUMBERS]
    if not all(isinstance(n, int | float) and not isinstance(n, bool) and n > 0 for n in numbers):
        raise ValueError("detection.json's numbers are above 0")
    wait, gap, keep, tick, lookback = (float(n) for n in numbers)
    return DetectionSettings(frozenset(raw["show_feed_on"]), gap, keep, tick, frozenset(raw["speak_on"]), wait,
                             frozenset(raw["look_now_on"]), lookback, frozenset(raw["speak_in_quiet_on"]))
