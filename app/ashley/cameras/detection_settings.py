"""What a camera's detector events do, as data (`detection.json`): `show_feed_on` the detector classes that put the
camera's live feed on the visible screens, `min_gap_s` the least time between two such feeds for one camera (counted
between the events' own times), `keep_s` how long a recorded detection is kept, and `tick_s` between the passes that
follow the cameras again, so a camera named or dropped is followed or let go within it."""

import json
from dataclasses import dataclass
from pathlib import Path

FILE = Path(__file__).with_name("detection.json")
_KEYS = ("show_feed_on", "min_gap_s", "keep_s", "tick_s")


@dataclass(frozen=True)
class DetectionSettings:
    show_feed_on: frozenset[str]
    min_gap_s: float
    keep_s: float
    tick_s: float


def load() -> DetectionSettings:
    """The tunables in `detection.json`. Raises ValueError unless it has exactly its four keys: classes (non-empty
    strings, which may be none) and three numbers above 0."""
    raw = json.loads(FILE.read_text())
    if set(raw) != set(_KEYS):
        raise ValueError(f"detection.json has exactly {', '.join(_KEYS)}")
    if not isinstance(raw["show_feed_on"], list) or not all(isinstance(c, str) and c for c in raw["show_feed_on"]):
        raise ValueError("detection.json's show_feed_on is a list of detector classes")
    numbers = [raw[k] for k in _KEYS[1:]]
    if not all(isinstance(n, int | float) and not isinstance(n, bool) and n > 0 for n in numbers):
        raise ValueError("detection.json's numbers are above 0")
    return DetectionSettings(frozenset(raw["show_feed_on"]), *(float(n) for n in numbers))
