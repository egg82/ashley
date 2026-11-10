"""Sign-in's lifetimes, as data in `signin.json` beside this module, validated when loaded.

A session lasts at most `session_days` from sign-in and ends sooner when unused for `idle_days`; its last use is
written at most every `touch_minutes`, so a run of requests costs one write. A sign-in in flight must come back within
`pending_minutes`, and at most `max_pending` may be in flight at once, which bounds what an anonymous flood of
sign-in starts can store. An account refused for want of a mapping is listed for the admin for
`unmapped_retention_days` after its last try."""

import json
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

FILE = Path(__file__).with_name("signin.json")


@dataclass(frozen=True)
class Policy:
    session_days: int
    idle_days: int
    touch_minutes: int
    pending_minutes: int
    max_pending: int
    unmapped_retention_days: int

    def __post_init__(self) -> None:
        if min(self.session_days, self.idle_days, self.touch_minutes, self.pending_minutes, self.max_pending,
               self.unmapped_retention_days) < 1:
            raise ValueError("signin.json values must be at least 1")
        if self.idle_days > self.session_days:
            raise ValueError("idle_days cannot outlast session_days")
        if self.touch_minutes >= self.idle_days * 1440:
            raise ValueError("touch_minutes must be well inside idle_days")


def parse(raw: dict[str, Any]) -> Policy:
    """A Policy from the decoded JSON. Raises ValueError naming a key that is missing, unknown or not a whole number."""
    expected = {f.name for f in fields(Policy)}
    if set(raw) != expected:
        raise ValueError(f"signin.json keys: missing {sorted(expected - set(raw))}, unknown {sorted(set(raw) - expected)}")
    for key, value in raw.items():
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"signin.json.{key} must be a whole number")
    return Policy(**raw)


def load(path: Path = FILE) -> Policy:
    return parse(json.loads(path.read_text(encoding="utf-8")))
