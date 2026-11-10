"""Whose voice one wake's utterance is, from the household's prints and presence (`decisions.md`, "A voice names the
speaker as a hint"). Pure: no I/O, no clock."""

import math
from dataclasses import dataclass
from typing import Literal

from ...inference.voiceprint import Voiceprint
from .voices import PersonPrints

Outcome = Literal["matched", "no_prints", "too_short", "below_floor", "close_second", "away"]
"""`matched` names a person; every other outcome names no one. `no_prints`: nobody in the household has a print by
the utterance's model. `too_short`: under `min_audio_ms`. `below_floor`: the best score is under `floor`.
`close_second`: the runner-up is within `margin` of the best. `away`: the best is someone presence knows is away."""

Agreement = Literal["yes", "no", "unknown"]
"""Whether presence agrees: when exactly one person is home, `yes` if the outcome is `matched` and names that person,
`no` if it names anyone else or names no one; `unknown` when presence is unknown or anything other than one person
is home."""


@dataclass(frozen=True)
class MatchPolicy:
    """The numbers in `voice.json`'s `speaker`: `floor` and `margin` are cosines (`floor` in [-1, 1], `margin` in
    [0, 2]), `min_audio_ms` is positive, and `decides` says whether a match names the speaker or is only logged."""

    floor: float
    margin: float
    min_audio_ms: int
    decides: bool


@dataclass(frozen=True)
class Match:
    """`person_id` is set only when `outcome` is `matched`. `best` and `second` are the top two people's scores,
    None when there was no one to score (`second` also None with only one person scored); `presence` is the
    `Agreement`."""

    outcome: Outcome
    person_id: int | None
    best: float | None
    second: float | None
    presence: Agreement


def match(voiceprint: Voiceprint, prints: tuple[PersonPrints, ...], home: frozenset[int] | None,
          policy: MatchPolicy) -> Match:
    """Score each person in `prints` as the cosine between `voiceprint.vector` and the mean of their vectors,
    renormalised to unit length; then decide in this order: `too_short` (before scoring anything, so `best` and
    `second` are None), `no_prints`, `below_floor`, `close_second` (best minus second under `margin`), `away` (the
    best is not in `home`, when `home` is known), else `matched`. A tie for best is `close_second` whatever
    `margin` is. Every vector in `prints` is the length of `voiceprint.vector`; raises ValueError when one is not.
    `policy.decides` does not change the result: the caller reads it."""
    if voiceprint.audio_ms < policy.min_audio_ms:
        return _decided("too_short", None, None, None, home)
    scores = sorted(((_cosine(voiceprint.vector, _centroid(p.vectors)), p.person_id)
                     for p in prints), reverse=True)
    if not scores:
        return _decided("no_prints", None, None, None, home)
    best, best_id = scores[0]
    second = scores[1][0] if len(scores) > 1 else None
    if best < policy.floor:
        return _decided("below_floor", None, best, second, home)
    if second is not None and (best == second or best - second < policy.margin):
        return _decided("close_second", None, best, second, home)
    if home is not None and best_id not in home:
        return _decided("away", None, best, second, home)
    return _decided("matched", best_id, best, second, home)


def _decided(outcome: Outcome, person_id: int | None, best: float | None, second: float | None,
             home: frozenset[int] | None) -> Match:
    if home is None or len(home) != 1:
        presence: Agreement = "unknown"
    else:
        presence = "yes" if person_id is not None and person_id in home else "no"
    return Match(outcome, person_id, best, second, presence)


def _centroid(vectors: tuple[tuple[float, ...], ...]) -> tuple[float, ...]:
    """The sum, which `_cosine` scores the same as the renormalised mean; `strict` raises on unequal lengths."""
    return tuple(sum(column) for column in zip(*vectors, strict=True))


def _cosine(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(x * x for x in b))
    return sum(x * y for x, y in zip(a, b, strict=True)) / norm if norm else 0.0
