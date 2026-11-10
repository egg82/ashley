"""When a conversation goes idle and when it closes: a pure function of its kind, its last activity and now, so every
threshold is data (`policy.json`) tuned from real use."""

import json
import math
from dataclasses import dataclass
from datetime import datetime
from importlib import resources
from typing import Any, get_args

from .model import Kind, State

KINDS: tuple[Kind, ...] = get_args(Kind)


@dataclass(frozen=True)
class Timing:
    """A conversation of one kind is open until `idle_after_s` have passed since its last activity, idle from then
    until `closed_after_s` have passed, and closed from then on. `0 < idle_after_s < closed_after_s`."""

    idle_after_s: float
    closed_after_s: float


@dataclass(frozen=True)
class Policy:
    """One `Timing` per kind; every kind has one."""

    timings: dict[Kind, Timing]

    def state_of(self, kind: Kind, last_activity_at: datetime, now: datetime) -> State:
        """`open` while less than `idle_after_s` has passed since `last_activity_at`, `idle` from exactly
        `idle_after_s` until `closed_after_s`, `closed` from exactly `closed_after_s` on. A `now` before
        `last_activity_at` (clocks disagreeing) counts as no time passed: `open`."""
        timing = self.timings[kind]
        elapsed = (now - last_activity_at).total_seconds()
        if elapsed < timing.idle_after_s:
            return "open"
        return "idle" if elapsed < timing.closed_after_s else "closed"


def load() -> Policy:
    """The policy shipped in `policy.json` beside this module. Raises ValueError when a kind is missing or a timing
    breaks `0 < idle_after_s < closed_after_s`."""
    return parse(json.loads(resources.files("ashley.conversations").joinpath("policy.json").read_text()))


def parse(data: object) -> Policy:
    """A policy from JSON already parsed: `{"<kind>": {"idle_after_s": n, "closed_after_s": n}, ...}`, one entry per
    kind and no others. Raises ValueError naming what is wrong otherwise."""
    entries = _object(data)
    if entries is None:
        raise ValueError("a policy is an object with one entry per kind")
    missing = [k for k in KINDS if k not in entries]
    extra = sorted(set(entries) - set(KINDS))
    if missing or extra:
        raise ValueError(f"policy kinds: missing {missing}, unknown {extra}")
    return Policy({kind: _timing(kind, entries[kind]) for kind in KINDS})


def _object(value: object) -> dict[str, object] | None:
    raw: Any = value
    if not hasattr(raw, "keys") or not all(type(key) is str for key in raw.keys()):
        return None
    return dict[str, object](raw)


def _timing(kind: str, entry: object) -> Timing:
    fields = _object(entry)
    if fields is None or set(fields) != {"idle_after_s", "closed_after_s"}:
        raise ValueError(f"{kind}: expected exactly idle_after_s and closed_after_s")
    idle = _seconds(kind, "idle_after_s", fields["idle_after_s"])
    closed = _seconds(kind, "closed_after_s", fields["closed_after_s"])
    if not 0 < idle < closed:
        raise ValueError(f"{kind}: need 0 < idle_after_s < closed_after_s")
    return Timing(idle, closed)


def _seconds(kind: str, name: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise ValueError(f"{kind}.{name}: expected a finite number")
    return float(value)

