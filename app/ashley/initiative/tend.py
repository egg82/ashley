"""Whether she tends her home channel on Discord in this slot of time (`decisions.md`, "Whether she speaks unprompted is
decided in code"): a seeded roll per server and slot, then a score from how long the channel has gone without her and
how many people wrote there since, never in the household's night or soon after her last message. The rates are data
(`tend.json` beside this module); every function here is pure, so whichever process decides a slot decides the same."""

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from .score import at_night, roll
from .weights import Weights

FILE = Path(__file__).with_name("tend.json")
HOUR_S = 3600.0

Verdict = Literal["allowed", "rolled_out", "unknown", "night", "recent", "low"]
"""What a slot came to: `allowed`, she is asked to tend it; `rolled_out`, the seeded roll missed the chance; `unknown`,
the channel or the household's zone could not be read; `night`, the slot starts in the household's night hours
(`score.json`'s `night`); `recent`, her last message there is younger than `min_gap_h`; `low`, the score is under the
threshold."""


@dataclass(frozen=True)
class Rates:
    """The loop looks every `check_every_s`; time is cut into slots of `slot_s`, each rolled once against `chance`.
    `min_gap_h` is the least time after her last message there; `read_count` (1 to 100), how many of the channel's
    latest messages the facts are measured from. The score is `quiet_weight` times the time since her last message as
    a share of `quiet_full_at_h`, plus `activity_weight` times people's messages since as a share of `activity_full_at`,
    each share at most 1; she tends at `threshold` or above."""

    check_every_s: float
    slot_s: float
    chance: float
    min_gap_h: float
    read_count: int
    threshold: float
    quiet_weight: float
    quiet_full_at_h: float
    activity_weight: float
    activity_full_at: int


@dataclass(frozen=True)
class Tending:
    """The facts at the start of a slot, measured from the messages sent before it. `seed` is `<device id>:<slot>`.
    `hour` is the slot's start in the household's zone, None when unknown; `known` is False when the channel could not
    be read; `since_mine_s` is how long before the slot her latest message there was, None when none of hers is among
    what was read; `people_since`, how many messages by people (not bots) came after it, among what was read."""

    seed: str
    hour: int | None
    known: bool
    since_mine_s: float | None
    people_since: int


def rolls(seed: str, rates: Rates) -> bool:
    """Whether the roll seeded by `seed` falls inside the chance. Checked before the channel is read."""
    return roll(f"tend:{seed}") < rates.chance


def score(tending: Tending, rates: Rates) -> float:
    """None of hers read counts as a full share of quiet."""
    since = tending.since_mine_s
    quiet = 1.0 if since is None else min(max(since, 0.0) / (rates.quiet_full_at_h * HOUR_S), 1.0)
    activity = min(tending.people_since / rates.activity_full_at, 1.0)
    return rates.quiet_weight * quiet + rates.activity_weight * activity


def verdict(tending: Tending, rates: Rates, weights: Weights) -> Verdict:
    """The first of: the roll missed; a fact unknown; night; too soon after her last message; a low score; else
    allowed."""
    if not rolls(tending.seed, rates):
        return "rolled_out"
    if tending.hour is None or not tending.known:
        return "unknown"
    if at_night(tending.hour, weights):
        return "night"
    if tending.since_mine_s is not None and tending.since_mine_s < rates.min_gap_h * HOUR_S:
        return "recent"
    if score(tending, rates) < rates.threshold:
        return "low"
    return "allowed"


def load(path: Path = FILE) -> Rates:
    """The rates in `path`. Raises ValueError for a missing or unknown key, a chance outside [0, 1], a span, weight or
    count that is not positive, or a `read_count` outside 1 to 100."""
    raw: Any = json.loads(path.read_text())
    loose: Any = raw
    keys = {"check_every_s", "slot_s", "chance", "min_gap_h", "read_count", "threshold", "quiet", "activity"}
    if not isinstance(raw, dict) or set(_keys(raw)) != keys:
        raise ValueError(f"tend.json has exactly {', '.join(sorted(keys))}")
    top: dict[str, Any] = loose
    quiet, activity = _pair(top, "quiet", "full_at_h"), _pair(top, "activity", "full_at")
    if not _number(top["chance"]) or not 0.0 <= top["chance"] <= 1.0:
        raise ValueError("chance is a number from 0 to 1")
    if not all(_positive(top[k]) for k in ("check_every_s", "slot_s", "min_gap_h", "threshold")):
        raise ValueError("check_every_s, slot_s, min_gap_h and threshold are positive")
    if isinstance(top["read_count"], bool) or not isinstance(top["read_count"], int) or not 1 <= top["read_count"] <= 100:
        raise ValueError("read_count is a whole number from 1 to 100")
    if isinstance(activity[1], bool) or not isinstance(activity[1], int):
        raise ValueError("activity.full_at is a whole number")
    return Rates(float(top["check_every_s"]), float(top["slot_s"]), float(top["chance"]), float(top["min_gap_h"]),
                 top["read_count"], float(top["threshold"]), float(quiet[0]), float(quiet[1]), float(activity[0]),
                 activity[1])


def _keys(raw: Any) -> list[str]:
    loose: dict[str, Any] = raw
    return list(loose)


def _pair(top: dict[str, Any], key: str, full: str) -> tuple[Any, Any]:
    part: Any = top[key]
    loose: Any = part
    if not isinstance(part, dict) or set(_keys(part)) != {"weight", full}:
        raise ValueError(f"{key} has exactly weight and {full}")
    fields: dict[str, Any] = loose
    if not _positive(fields["weight"]) or not _positive(fields[full]):
        raise ValueError(f"{key}.weight and {key}.{full} are positive")
    return fields["weight"], fields[full]


def _number(raw: Any) -> bool:
    return not isinstance(raw, bool) and isinstance(raw, int | float) and math.isfinite(raw)


def _positive(raw: Any) -> bool:
    return _number(raw) and raw > 0


RATES = load()
