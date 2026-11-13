"""An event loop whose clock jumps: whenever nothing is ready to run, its clock moves straight to the next timer, so
code that sleeps, times out or waits out a lease takes no wall time. For code that waits only on timers: a socket or
a thread is not waited for before the clock jumps past it. Code that never waits never lets the clock move, so a busy
loop is stopped by a wall-clock guard instead."""

import asyncio
import selectors
import time
from collections.abc import Coroutine
from typing import Any


WALL_LIMIT_S = 5.0


class BusyLoop(Exception):
    """The loop ran WALL_LIMIT_S of wall clock without its own clock reaching the scenario's limit: something spins."""


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0
        self.wall_deadline = time.monotonic() + WALL_LIMIT_S


class _JumpSelector(selectors.DefaultSelector):
    def __init__(self, clock: _Clock) -> None:
        super().__init__()
        self._clock = clock

    def select(self, timeout: float | None = None) -> list[tuple[selectors.SelectorKey, int]]:
        if time.monotonic() > self._clock.wall_deadline:
            raise BusyLoop(f"{WALL_LIMIT_S}s of wall clock passed at {self._clock.now:.2f}s on the loop's clock")
        if timeout is None or timeout <= 0:
            return super().select(timeout)
        ready = super().select(0)
        if not ready:
            self._clock.now += timeout
        return ready


class VirtualTimeLoop(asyncio.SelectorEventLoop):
    def __init__(self) -> None:
        self._clock = _Clock()
        super().__init__(_JumpSelector(self._clock))

    def time(self) -> float:
        return self._clock.now


def run(scenario: Coroutine[Any, Any, None], limit: float = 60.0) -> None:
    """Run `scenario` on a `VirtualTimeLoop`, failing it once `limit` seconds of its clock have passed."""
    with asyncio.Runner(loop_factory=VirtualTimeLoop) as runner:
        runner.run(asyncio.wait_for(scenario, limit))
