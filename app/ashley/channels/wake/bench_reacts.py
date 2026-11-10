"""She reacts to a person's changes on a bench: part of the `wakes` singleton's sweep, so it runs under the same lease
(`runner`). Every sweep, `Workshop.unseen` names the open benches where a person's commands, after the last she has
seen, have been quiet for `pause_s`; each gets one turn on its own thread (`bench_react_turn`) through the shared turn
loop, so it is checkpointed and any pod on either site can finish it. A bench that reacted `max_reactions` times in
`window_s` waits. Her reply carries `worth_saying`, which `Initiative` decides on: false stores her staying quiet and
posts nothing.

The reaction is recorded (`Workshop.reacted`) once the turn is handed to the loop, which is also what moves the mark of
the last command she has seen. A runner killed before then hands the same changes in again, and the turn's `source`
makes it the same turn; one killed after leaves the turn to the loop's own resume.

Logs `bench_reacts.done` with the bench id, how many commands were handed, `reply`, `none` or `pending`, and
duration_ms; `bench_reacts.capped` once per run of sweeps a bench waits, with the bench id and how long;
`bench_reacts.deferred` with the bench id and the reason; `bench_reacts.refused`. Never a piece or a message."""

import logging
import time

from ... import logs, services
from ...people.zone import zone_of
from ...workshop.reactions import Unseen
from ...workshop.workshop import Workshop, WorkshopUnavailable
from ..respond import RespondRefused, RespondUnavailable, respond
from .bench_react_config import CONFIG
from .bench_react_turn import inbound

log = logging.getLogger("ashley.channels.wake")


def wait_s(ages: tuple[float, ...]) -> float:
    """How long until the bench may react again, from the seconds since each reaction in the window, newest first: 0
    while it has fewer than `max_reactions` in it."""
    if len(ages) < CONFIG.max_reactions:
        return 0.0
    return CONFIG.window_s - ages[CONFIG.max_reactions - 1]


class BenchReacts:
    """The sweep, and which benches it has already said are waiting, so a wait is logged once however often it looks."""

    def __init__(self) -> None:
        self._waiting: set[int] = set()
        self._down = False

    async def sweep(self) -> int:
        """React to the quiet benches, up to `batch` of them; how many were reacted to."""
        try:
            quiet = await services.get(Workshop).unseen(CONFIG.pause_s, CONFIG.scan, CONFIG.listed)
            reacted = await self._react(quiet)
        except WorkshopUnavailable:
            if not self._down:
                logs.warning(log, "bench_reacts.unavailable")
            self._down = True
            return 0
        self._down = False
        self._waiting &= {u.bench_id for u in quiet}
        return reacted

    async def _react(self, quiet: tuple[Unseen, ...]) -> int:
        reacted = 0
        for unseen in quiet:
            if reacted == CONFIG.batch:
                break
            wait = wait_s(await services.get(Workshop).reaction_ages(unseen.bench_id, CONFIG.window_s))
            if wait > 0:
                if unseen.bench_id not in self._waiting:
                    logs.info(log, "bench_reacts.capped", bench=unseen.bench_id, wait_s=int(wait))
                self._waiting.add(unseen.bench_id)
            elif await _reacted(unseen):
                reacted += 1
        return reacted


async def _reacted(unseen: Unseen) -> bool:
    started = time.perf_counter()
    zone = await zone_of(unseen.household_id)
    if zone is None:
        logs.warning(log, "bench_reacts.deferred", bench=unseen.bench_id, reason="PeopleUnavailable")
        return False
    try:
        out = await respond(inbound(unseen, zone))
        what = "pending" if out.follows else "none" if out.quiet else "reply"
    except RespondRefused:
        logs.warning(log, "bench_reacts.refused", bench=unseen.bench_id)
        what = "refused"
    except RespondUnavailable:
        logs.warning(log, "bench_reacts.deferred", bench=unseen.bench_id, reason="RespondUnavailable")
        return False
    await services.get(Workshop).reacted(unseen.household_id, unseen.bench_id, unseen.to_seq, CONFIG.keep_s)
    logs.info(log, "bench_reacts.done", bench=unseen.bench_id, commands=unseen.count, outcome=what,
              duration_ms=int((time.perf_counter() - started) * 1000))
    return True
