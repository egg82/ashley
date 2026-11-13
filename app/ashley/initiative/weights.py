"""The initiative score's weights, thresholds and odds: data in `score.json` beside this module, tuned from real use.

Each weight's sign is part of the data's contract, so a typo cannot turn a recent greeting into a reason to greet:
time since she last heard from the person may only raise the score; the night, others at home, a recent greeting and a
recent word of hers may only lower it. A fact scores in full past its span (`full_at_s`, `cap`) and a recent turn
fades to nothing over its `within_s`. A score under `threshold` is silent without a roll; one that clears it rolls
against the odds of the highest band whose `from` it reaches."""

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

FILE = Path(__file__).with_name("score.json")
_TOP = {"threshold", "heard", "night", "others_home", "greeted", "spoke", "odds"}


@dataclass(frozen=True)
class Band:
    """The odds of each outcome for a score of at least `start`; they sum to 1."""

    start: float
    full: float
    short: float
    silent: float


@dataclass(frozen=True)
class Weights:
    threshold: float
    heard: float
    heard_full_at_s: float
    night: float
    night_from: int
    night_to: int
    others_home: float
    others_cap: int
    greeted: float
    greeted_within_s: float
    spoke: float
    spoke_within_s: float
    bands: tuple[Band, ...]


def load(path: Path = FILE) -> Weights:
    """The weights in `path`. Raises ValueError for anything `parse` refuses, or text that is not JSON."""
    return parse(json.loads(path.read_text()))


def parse(raw: Any) -> Weights:
    """`raw` as weights. Raises ValueError for a missing or unknown key, a value that is not a finite number, a weight
    of the wrong sign, a span that is not positive, an hour off the clock, or odds that do not cover every score that
    clears the threshold with outcomes summing to 1."""
    top = _keys(raw, _TOP, "the score")
    heard = _keys(top["heard"], {"weight", "full_at_s"}, "heard")
    night = _keys(top["night"], {"weight", "from_hour", "to_hour"}, "night")
    others = _keys(top["others_home"], {"weight", "cap"}, "others_home")
    greeted = _keys(top["greeted"], {"weight", "within_s"}, "greeted")
    spoke = _keys(top["spoke"], {"weight", "within_s"}, "spoke")
    threshold = _number(top["threshold"], "threshold")
    return Weights(threshold, _sign(heard["weight"], 1, "heard"), _positive(heard["full_at_s"], "heard.full_at_s"),
                   _sign(night["weight"], -1, "night"), _hour(night["from_hour"]), _hour(night["to_hour"]),
                   _sign(others["weight"], -1, "others_home"), _count(others["cap"]),
                   _sign(greeted["weight"], -1, "greeted"), _positive(greeted["within_s"], "greeted.within_s"),
                   _sign(spoke["weight"], -1, "spoke"), _positive(spoke["within_s"], "spoke.within_s"),
                   _bands(top["odds"], threshold))


def _keys(raw: Any, keys: set[str], what: str) -> dict[str, Any]:
    loose: Any = raw
    if not isinstance(raw, dict) or set(loose) != keys:
        raise ValueError(f"{what} has exactly {', '.join(sorted(keys))}")
    out: dict[str, Any] = loose
    return out


def _number(raw: Any, what: str) -> float:
    if isinstance(raw, bool) or not isinstance(raw, int | float) or not math.isfinite(raw):
        raise ValueError(f"{what} is a finite number")
    return float(raw)


def _sign(raw: Any, sign: int, what: str) -> float:
    value = _number(raw, what)
    if value * sign < 0:
        raise ValueError(f"{what} may only {'raise' if sign > 0 else 'lower'} the score")
    return value


def _positive(raw: Any, what: str) -> float:
    value = _number(raw, what)
    if value <= 0:
        raise ValueError(f"{what} is positive")
    return value


def _hour(raw: Any) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int) or not 0 <= raw <= 23:
        raise ValueError("an hour is a whole number from 0 to 23")
    return raw


def _count(raw: Any) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 1:
        raise ValueError("others_home.cap is a whole number of at least 1")
    return raw


def _bands(raw: Any, threshold: float) -> tuple[Band, ...]:
    loose: Any = raw
    if not isinstance(raw, list) or not loose:
        raise ValueError("odds is a non-empty list of bands")
    items: list[Any] = loose
    bands = tuple(_band(b) for b in items)
    if bands[0].start != threshold:
        raise ValueError("the first band starts at the threshold")
    if any(a.start >= b.start for a, b in zip(bands, bands[1:])):
        raise ValueError("bands start in rising order")
    return bands


def _band(raw: Any) -> Band:
    band = _keys(raw, {"from", "full", "short", "silent"}, "a band")
    odds = [_number(band[k], f"a band's {k}") for k in ("full", "short", "silent")]
    if min(odds) < 0 or not math.isclose(sum(odds), 1.0, abs_tol=1e-9):
        raise ValueError("a band's odds are not negative and sum to 1")
    return Band(_number(band["from"], "a band's from"), *odds)


WEIGHTS = load()
