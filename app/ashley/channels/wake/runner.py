"""The `wakes` singleton, under the lease: every `poll_s` it takes up to `batch` due wakes (`Wakes.due`), the longest
due first, and settles each with what came of it. A reminder fires (`reminder.fired`) and, when it repeats, is settled
with its next occurrence, which the settle stores only if it was the one to settle it; it never expires. A watch's wake (`watch_turn`) is told for the watches' `wake_max_age_s`, a day, then `expired`.
A house wake past `max_age_s` since it arrived, `expired`; no rule or more than one for its
event (`rule.rule_for`), `no_rule` or `ambiguous`; no person of the household for its `who`, `no_person`; else, for a rule
that greets (`WakeRule.greets`), the facts of its moment are gathered (`moment.gathered`) and `Initiative` plans from
them, and her turn runs through the shared turn loop with that plan's instruction, if any (`wake_turn.inbound`), and it
is `turn`, or `failed` when the model refused it. A
wake whose rule or person cannot be read now (the workshop or People out of reach), or whose turn could not run now
(`RespondUnavailable`, as during a failover), is left due for the next sweep, until `max_age_s`; handing it in again
is the same turn (`Inbound.source`).
Each sweep also lets her react to benches whose person has paused (`bench_reacts`), under the same lease.
Settled wakes older than `keep_s` are pruned each sweep. Tunables are data, `wakes.json` beside this module (`config`).

A runner killed during a turn leaves its wake due: the next sweep hands it in again, and the turn loop makes that the
same turn (`Inbound.source`), finished by whichever runner holds its work.

Logs `wakes.settled` with the wake and household ids, its kind, the outcome, whether a next occurrence was stored,
age_ms and duration_ms; `wakes.pruned` with the
count when any were; `wakes.deferred` with the wake id and the reason; `wakes.unavailable` once per run of sweeps that
could not reach the wakes. Never a field of the wake."""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import datetime

from ... import logs, services
from ...initiative.initiative import Initiative
from ...people.model import Person
from ...people.people import People, PeopleUnavailable
from ...senses.home_assistant_presence import SYSTEM
from ...senses.wakes import Due, Outcome, Reminder, Wake, Wakes, WakesUnavailable, WatchWake
from ...watches.watches import WatchesUnavailable
from ...workshop.workshop import WorkshopUnavailable
from ..devices import DevicesUnavailable
from ..respond import RespondRefused, RespondUnavailable, respond
from . import reminder, wake_turn, watch_turn
from .bench_reacts import BenchReacts
from .config import CONFIG
from .moment import gathered
from .rule import rule_for

log = logging.getLogger("ashley.channels.wake")

NAME = "wakes"




async def run(sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> None:
    """Sweep every `poll_s` until cancelled."""
    failing = False
    benches = BenchReacts()
    while True:
        try:
            await sweep()
            await benches.sweep()
        except WakesUnavailable:
            if not failing:
                logs.warning(log, "wakes.unavailable")
            failing = True
        else:
            failing = False
        await sleep(CONFIG.poll_s)


async def sweep() -> int:
    """Take up the due wakes one after another, then prune; how many were due. Raises WakesUnavailable."""
    wakes = services.get(Wakes)
    due = await wakes.due(CONFIG.batch)
    for wake in due:
        await _taken(wake)
    pruned = await wakes.prune(CONFIG.keep_s)
    if pruned:
        logs.info(log, "wakes.pruned", count=pruned)
    return len(due)


async def _taken(due: Due) -> None:
    started = time.perf_counter()
    try:
        outcome, next_due = await _outcome(due)
    except (WorkshopUnavailable, PeopleUnavailable, DevicesUnavailable, RespondUnavailable, WatchesUnavailable) as e:
        logs.warning(log, "wakes.deferred", wake=due.id, reason=type(e).__name__)
        return
    if await _fires_again(due, outcome):
        return
    settled = await services.get(Wakes).settle(due.id, outcome, next_due)
    logs.info(log, "wakes.settled", wake=due.id, household=due.wake.household_id,
              kind=_kind(due.wake), outcome=outcome,
              next=settled and next_due is not None, age_ms=int(due.age_s * 1000),
              duration_ms=int((time.perf_counter() - started) * 1000))


async def _fires_again(due: Due, outcome: Outcome) -> bool:
    """A reminder whose firing could not run is due again `retry_s` on, until it has been fired `fire_attempts` times;
    whether it was."""
    if not isinstance(due.wake, Reminder) or outcome not in ("failed", "no_person"):
        return False
    fired = await services.get(Wakes).refire(due.id, CONFIG.retry_s)
    if fired == 0 or fired >= CONFIG.fire_attempts:
        return False
    logs.warning(log, "wakes.refire", wake=due.id, outcome=outcome, attempt=fired)
    return True


async def _outcome(due: Due) -> tuple[Outcome, datetime | None]:
    if isinstance(due.wake, Reminder):
        return await reminder.fired(due.id, due.wake)
    if isinstance(due.wake, WatchWake):
        return await watch_turn.fired(due.id, due.wake, due.age_s), None
    return await _house(due, due.wake), None


def _kind(wake: Wake | Reminder | WatchWake) -> str:
    return "reminder" if isinstance(wake, Reminder) else "watch" if isinstance(wake, WatchWake) else "house"


async def _house(due: Due, wake: Wake) -> Outcome:
    if due.age_s > CONFIG.max_age_s:
        return "expired"
    rule = await rule_for(wake.household_id, wake.event)
    if isinstance(rule, str):
        return rule
    person = await _person(wake)
    if person is None:
        return "no_person"
    moment = await gathered(due.id, wake, person) if rule.greets else None
    outcome = None if moment is None else services.get(Initiative).planned(moment).outcome
    try:
        await respond(wake_turn.inbound(due.id, wake, rule, person, moment, outcome))
    except RespondRefused:
        return "failed"
    return "turn"


async def _person(wake: Wake) -> Person | None:
    if wake.who is None:
        return None
    found = await services.get(People).person_for(SYSTEM, wake.who)
    return found if found is not None and found.household_id == wake.household_id else None
