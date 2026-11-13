"""Whether she may make a remark nobody asked for (an aside, `decisions.md`, "Whether she speaks unprompted is decided
in code"): a seeded roll against a chance, a cap per person per day counted from what she sent, never while the
person is focused, and never a line she already sent. The rates are data (`remark.json` beside this module); every
function here is pure, so the first runner and a resumer decide the same."""

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from .score import at_night, roll
from .weights import Weights

FILE = Path(__file__).with_name("remark.json")
DAY_S = 86400.0

Verdict = Literal["allowed", "rolled_out", "unknown", "night", "typing", "capped"]
"""What a chance came to: `allowed`, she is asked for a remark; `rolled_out`, the seeded roll missed the chance;
`unknown`, a fact the cap or focus needs could not be read, so she stays out of it; `night`, the household's night
hours (`score.json`'s `night`); `typing`, the person typed into a Claude Code session of theirs within
`typing_within_s`; `capped`, she already made `per_day` remarks for them in the last day."""


@dataclass(frozen=True)
class Rates:
    """`chance` in [0, 1] that a message rolls a remark; at most `per_day` remarks per person in any 24 hours;
    `typing_within_s`, how recently typing into a session counts as focus; `repeat_within_days`, how far back a line
    she sent counts as already said. Remarks are kept that long, and at least a day."""

    chance: float
    per_day: int
    typing_within_s: float
    repeat_within_days: int

    @property
    def keep_s(self) -> float:
        return max(self.repeat_within_days * DAY_S, DAY_S)


@dataclass(frozen=True)
class Chance:
    """The facts at a message she could remark on, gathered before her turn. `seed` is the message's stable id
    (`discord:<message id>`), so a message handed in twice rolls the same. `hour` is now in the household's zone, None
    when unknown; `sent`, the remarks she made for the person in the last day that went out or may yet, None when they
    could not be read; `since_typed_s`, how long since the person last typed into a Claude Code session, None when she
    sees no typing (no bridge, or it records none); `typing_known` is False when their bridge could not be read;
    `said`, the fingerprints (`fingerprint`) of the lines she sent as remarks within `repeat_within_days`."""

    seed: str
    hour: int | None
    sent: int | None
    since_typed_s: float | None
    typing_known: bool
    said: tuple[str, ...] = ()


def rolls(seed: str, rates: Rates) -> bool:
    """Whether the roll seeded by `seed` falls inside the chance. Checked before any fact is read."""
    return roll(f"remark:{seed}") < rates.chance


def verdict(chance: Chance, rates: Rates, weights: Weights) -> Verdict:
    """The first of: the roll missed; a fact unknown; night; typing; capped; else allowed."""
    if not rolls(chance.seed, rates):
        return "rolled_out"
    if chance.hour is None or chance.sent is None or not chance.typing_known:
        return "unknown"
    if at_night(chance.hour, weights):
        return "night"
    if chance.since_typed_s is not None and chance.since_typed_s < rates.typing_within_s:
        return "typing"
    if chance.sent >= rates.per_day:
        return "capped"
    return "allowed"


def fingerprint(line: str) -> str:
    """`line` with case, punctuation and spacing ignored, hashed: two lines that differ only in those match."""
    words = "".join(c if c.isalnum() else " " for c in line.casefold()).split()
    return hashlib.sha256(" ".join(words).encode()).hexdigest()


def repeats(line: str, chance: Chance) -> bool:
    return fingerprint(line) in chance.said


def load(path: Path = FILE) -> Rates:
    """The rates in `path`. Raises ValueError for a missing or unknown key, a chance outside [0, 1], a cap that is not
    a whole number of at least 0, or a span that is not positive."""
    raw: Any = json.loads(path.read_text())
    loose: Any = raw
    keys = {"chance", "per_day", "typing_within_s", "repeat_within_days"}
    if not isinstance(raw, dict) or set(loose) != keys:
        raise ValueError(f"remark.json has exactly {', '.join(sorted(keys))}")
    top: dict[str, Any] = loose
    chance, within = top["chance"], top["typing_within_s"]
    if not _number(chance) or not 0.0 <= chance <= 1.0:
        raise ValueError("chance is a number from 0 to 1")
    if not _whole(top["per_day"], 0) or not _whole(top["repeat_within_days"], 1):
        raise ValueError("per_day is a whole number of at least 0, repeat_within_days of at least 1")
    if not _number(within) or within <= 0:
        raise ValueError("typing_within_s is positive")
    return Rates(float(chance), top["per_day"], float(within), top["repeat_within_days"])


def _number(raw: Any) -> bool:
    return not isinstance(raw, bool) and isinstance(raw, int | float) and math.isfinite(raw)


def _whole(raw: Any, least: int) -> bool:
    return not isinstance(raw, bool) and isinstance(raw, int) and raw >= least


RATES = load()
