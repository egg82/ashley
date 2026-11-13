"""The initiative score of a moment and the seeded roll it makes (`decisions.md`, "Whether she speaks unprompted is
decided in code"): pure functions of a `Moment` and the `Weights`, so the same wake always plans the same."""

import hashlib
from dataclasses import replace

from .moment import Moment, Plan
from .weights import Band, Weights


def score(moment: Moment, weights: Weights) -> float:
    """The sum of each known fact's weight, scaled by how much of the fact there is. An unknown fact adds nothing."""
    total = 0.0
    if moment.since_heard_s is not None:
        total += weights.heard * min(max(moment.since_heard_s, 0.0) / weights.heard_full_at_s, 1.0)
    if moment.hour is not None and at_night(moment.hour, weights):
        total += weights.night
    if moment.others_home is not None:
        total += weights.others_home * min(moment.others_home, weights.others_cap) / weights.others_cap
    total += _recent(moment.since_greeted_s, weights.greeted, weights.greeted_within_s)
    total += _recent(moment.since_spoke_s, weights.spoke, weights.spoke_within_s)
    return total


def roll(seed: str) -> float:
    """A number in [0, 1) fixed by `seed` alone, the same in every process."""
    digest = hashlib.sha256(f"initiative:{seed}".encode()).digest()
    return int.from_bytes(digest[:8], "big") / 2**64


def planned(moment: Moment, weights: Weights) -> Plan:
    """Silent with no roll when the score is under the threshold; else the outcome the seeded roll picks from the odds
    of the score's band."""
    got = score(moment, weights)
    if got < weights.threshold:
        return Plan(got, None, "silent")
    rolled = roll(moment.seed)
    band = _band(got, weights)
    outcome = "full" if rolled < band.full else "short" if rolled < band.full + band.short else "silent"
    return Plan(got, rolled, outcome) if outcome == "silent" else _placed(Plan(got, rolled, outcome), moment)


def _placed(plan: Plan, moment: Moment) -> Plan:
    """`plan` said at the moment's satellite when it has one (the person is in that room), else at its screen, else the
    phone. Two arrivals are two wakes, each planned and placed on its own."""
    for route in ("room", "screen"):
        found = next((c for c in moment.devices if c.route == route), None)
        if found is not None:
            return replace(plan, route=found.route, device_id=found.device_id)
    return plan


def at_night(hour: int, weights: Weights) -> bool:
    """Whether `hour` is inside the weights' night hours, which may run across midnight."""
    start, end = weights.night_from, weights.night_to
    return start <= hour < end if start < end else hour >= start or hour < end


def _recent(since_s: float | None, weight: float, within_s: float) -> float:
    if since_s is None or since_s >= within_s:
        return 0.0
    return weight * (1.0 - max(since_s, 0.0) / within_s)


def _band(got: float, weights: Weights) -> Band:
    return [b for b in weights.bands if b.start <= got][-1]
