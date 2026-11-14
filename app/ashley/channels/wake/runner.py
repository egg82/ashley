"""The `wakes` singleton, under the lease: every `poll_s` it takes up to `batch` due wakes (`Wakes.due`), the longest
due first, and settles each with what came of it. A reminder fires (`reminder.fired`) and, when it repeats, is settled
with its next occurrence, which the settle stores only if it was the one to settle it; it never expires. A watch's wake (`watch_turn`) is told for the watches' `wake_max_age_s`, a day, then `expired`.
A house wake past `max_age_s` since it arrived, `expired`; no rule for it, or more than one
at the top (`rule.rule_for`), `no_rule` or `ambiguous`; no person of the household for its `who`, `no_person`; else, for a rule
that greets (`WakeRule.greets`), the facts of its moment are gathered (`moment.gathered`) and `Initiative` plans from
them, which may place the greeting at a satellite or screen of the place the wake names (recorded on the wake, so the
singletons that deliver reminders deliver it), or, when the rule names a paired kiosk of the household (`_kiosk`),
at that kiosk, announced there, or, when the rule names a speaker the household's house lists
(`speaker.listed`), at that speaker instead of any placement, and her turn runs through the shared turn loop with
that plan's instruction, if any (`wake_turn.inbound`), and it is `turn`, or `failed` when the model refused it. A
wake whose rule or person cannot be read now (the workshop or People out of reach), or whose turn could not run now
(`RespondUnavailable`, as during a failover), is left due for the next sweep, until `max_age_s`; handing it in again
is the same turn (`Inbound.source`).
Each sweep also lets her react to benches whose person has paused (`bench_reacts`), under the same lease.
Settled wakes older than `keep_s` are pruned each sweep. Tunables are data, `wakes.json` beside this module (`config`).

A runner killed during a turn leaves its wake due: the next sweep hands it in again, and the turn loop makes that the
same turn (`Inbound.source`), finished by whichever runner holds its work.

Logs `wakes.settled` with the wake and household ids, its kind, the outcome, whether a next occurrence was stored,
age_ms and duration_ms; `wakes.pruned` with the
count when any were; `wakes.placed` with the wake id, route and device id of a greeting placed at a device;
`wakes.device` with the wake id and household id and whether the kiosk a rule names was `named` or `unknown`;
`wakes.deferred` with the wake id and the reason; `wakes.unavailable` once per run of sweeps that
could not reach the wakes. Never a field of the wake."""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import datetime

from ... import logs, services
from ...initiative.initiative import Initiative
from ...initiative.moment import Plan
from ...people.model import Person
from ...people.people import People, PeopleUnavailable
from ...senses.home_assistant_presence import SYSTEM
from ...senses.house_lists import HouseUnreadable
from ...senses.wakes import Due, Outcome, Reminder, Route, Wake, Wakes, WakesUnavailable, WatchWake
from ...watches.watches import WatchesUnavailable
from ...workshop.wake_rule import WakeRule
from ...workshop.workshop import WorkshopUnavailable
from ..devices import DevicesUnavailable
from ..model import Device
from ..respond import RespondRefused, RespondUnavailable, respond
from . import reminder, reminder_device, speaker, wake_turn, watch_turn
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
    except (WorkshopUnavailable, PeopleUnavailable, DevicesUnavailable, RespondUnavailable, WatchesUnavailable,
            HouseUnreadable) as e:
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
    rule = await rule_for(due.id, wake)
    if isinstance(rule, str):
        return rule
    person = await _person(wake)
    if person is None:
        return "no_person"
    moment = await gathered(due.id, wake, person) if rule.greets else None
    plan = None if moment is None else services.get(Initiative).planned(moment)
    named = await _named(due.id, wake, rule)
    kiosk = await _kiosk(due.id, wake, rule)
    at = None if named or kiosk else await _placed(due.id, wake, person, plan)
    try:
        await respond(wake_turn.inbound(due.id, wake, rule, person, moment, None if plan is None else plan.outcome,
                                        at or kiosk, named, kiosk is not None))
    except RespondRefused:
        return "failed"
    return "turn"


async def _named(wake_id: int, wake: Wake, rule: WakeRule) -> str | None:
    """The speaker `rule` names when the household's house lists it as a media player; None for the phone.
    Raises HouseUnreadable."""
    if rule.speaker is None or not await speaker.listed(wake_id, wake.household_id, rule.speaker):
        return None
    return rule.speaker


async def _kiosk(wake_id: int, wake: Wake, rule: WakeRule) -> tuple[Route, Device] | None:
    """The screen and device the rule names when it is still a paired kiosk of the household; None for the phone.
    Raises DevicesUnavailable."""
    if rule.device is None:
        return None
    listed = await reminder_device.named(wake.household_id, "screen", rule.device)
    logs.info(log, "wakes.device", wake=wake_id, household=wake.household_id,
              outcome="named" if listed else "unknown")
    return None if listed is None else ("screen", listed.device)


async def _placed(wake_id: int, wake: Wake, person: Person, plan: Plan | None) -> tuple[Route, Device] | None:
    """The device a greeting is said at, recorded on the wake so it is delivered as a reminder is; None for the phone,
    which is also where one goes whose device is gone or no longer fits. Raises DevicesUnavailable, WakesUnavailable."""
    if plan is None or plan.route is None or plan.device_id is None:
        return None
    listed = await reminder_device.named(wake.household_id, plan.route, plan.device_id)
    if listed is None:
        return None
    await services.get(Wakes).routed(wake_id, person.id, plan.route, listed.device.id)
    logs.info(log, "wakes.placed", wake=wake_id, route=plan.route, device=listed.device.id)
    return plan.route, listed.device


async def _person(wake: Wake) -> Person | None:
    if wake.who is None:
        return None
    found = await services.get(People).person_for(SYSTEM, wake.who)
    return found if found is not None and found.household_id == wake.household_id else None
