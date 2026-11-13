"""What Initiative decides from on a turn she starts herself: the facts of the moment, gathered by the caller before the
turn (`Moment`), and what the score and the roll made of them (`Plan`)."""

from dataclasses import dataclass
from typing import Literal, get_args

Outcome = Literal["full", "short", "silent"]
"""What the roll made of a moment: `full`, she says it as she would; `short`, one short line; `silent`, nothing goes
out, though her turn still runs and may act."""

OUTCOMES: tuple[Outcome, ...] = get_args(Outcome)


Reach = Literal["room", "screen"]
"""Where a greeting can be said other than the phone: `room`, aloud through a satellite; `screen`, shown on a screen."""


@dataclass(frozen=True)
class Candidate:
    """A device at the place the person arrived that can carry a greeting: `device_id` and the `route` it carries."""

    route: Reach
    device_id: int


@dataclass(frozen=True)
class Moment:
    """The facts at a wake, each None when it could not be known, which scores as nothing rather than as a value.
    `seed` is the stable id the roll is seeded from (`wake:<id>`), so a replay of the same wake decides the same.
    `hour` is the hour the event happened in the household's zone; `others_home` how many others of the household are
    home; `since_heard_s` how long before the event the person last spoke to her; `since_greeted_s` how long since her
    last turn on a wake of the same event about the same person, kept quiet or not; `since_spoke_s` how long since her
    last wake turn about them that went out. `devices` are those at the place the wake names (`Wake.what`) that can carry
    a greeting; none means the phone."""

    seed: str
    hour: int | None = None
    others_home: int | None = None
    since_heard_s: float | None = None
    since_greeted_s: float | None = None
    since_spoke_s: float | None = None
    devices: tuple[Candidate, ...] = ()


@dataclass(frozen=True)
class Plan:
    """What the moment came to before her turn runs: its `score`, the `roll` in [0, 1) that picked the outcome (None when
    the score did not clear the threshold, and nothing was rolled), the `outcome`, and, when it is not silent and a
    device of the moment can carry it, the `device_id` it is said on and its `route`; None for the phone."""

    score: float
    roll: float | None
    outcome: Outcome
    route: Reach | None = None
    device_id: int | None = None
