"""When a turn started and what its kind's limits are: the clock the tool loop reads before each step."""

from collections.abc import Callable
from dataclasses import dataclass

from .limits import Limits
from .model import Medium


@dataclass
class Pace:
    """When the turn started, by `clock`, and its kind's limits; `wraps` when a refusal is wrapped up (`refused`), as one is
    after the turn's first line went out. `windows`: the fresh windows the turn has taken (`windows.taken`)."""

    started: float
    clock: Callable[[], float]
    limits: Limits
    medium: Medium
    wraps: bool = False
    windows: int = 0

    def restart(self) -> None:
        """A fresh window: the clock counts from now and `windows` is one more."""
        self.started = self.clock()
        self.windows += 1

    def past(self, seconds: float) -> bool:
        return self.clock() - self.started >= seconds

    def left(self, seconds: float) -> float:
        return max(0.0, seconds - (self.clock() - self.started))

    def ms(self) -> int:
        return int((self.clock() - self.started) * 1000)


def pace(limits: Limits, started: float | None, clock: Callable[[], float], medium: Medium,
         wraps: bool = False) -> Pace:
    return Pace(clock() if started is None else started, clock, limits, medium, wraps)
