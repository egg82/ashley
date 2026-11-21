"""The shadow job: what keeps shadow runs (`shadow`) going, run by the watches singleton under its lease, so on one site
at a time and holding the one set of Home Assistant sockets (`held_states.HeldStates.events`). Each pass subscribes the
households with a run still running to the events a run needs, records each as it arrives (`shadows.Shadows`), ends the
runs whose time has come by the Undo of their Install, as the person who approved it, and prunes old firings. An end
whose Undo is refused (the bench is closed, or the command is past the undo window) is taken out of the house directly,
by the shadow's own id (`remove`, which refuses any id that is not a shadow's: a shadow is only ever hers, so it needs no
person's approval); a delete that fails leaves the run running and is tried again on the next pass, until it succeeds or
Home Assistant has no such automation.

The run's end time lives in the database, so a pod that stopped leaves nothing for another to forget.

Logs `workshop.shadow_tick` (households, ended, retry, pruned, unreachable), `workshop.shadow_remove_failed` (bench, seq) when anything was done, and
`workshop.shadow_firing` (bench, piece, kind) per recorded event. Never an entity id or an event's data."""

import asyncio
import logging
from collections import Counter
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from .. import logs, services
from ..home_assistant.held_states import HeldStates, HouseEvent, Recorder
from ..home_assistant.homes import HomesUnavailable, house_of
from ..home_assistant.house import House, HouseRejected, HouseUnavailable
from . import shadow
from .commands import Undo
from .install_piece import automation_id_for, carry_out
from .installs import InstallsUnavailable
from .model import By, Owner
from .shadows import NewShadow, Shadows, ShadowsUnavailable
from .workshop import Workshop, WorkshopError

log = logging.getLogger("ashley.workshop")
TRIGGERED = "automation_triggered"


async def run(settings: shadow.Settings | None = None,
              sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> None:
    """Pass every `tick_s` until cancelled. Never raises but CancelledError."""
    settings = settings or shadow.load()
    watching: set[int] = set()
    while True:
        try:
            await tick(datetime.now(UTC), watching)
        except ShadowsUnavailable:
            logs.warning(log, "workshop.shadow_unavailable")
        await sleep(settings.tick_s)


async def tick(now: datetime, watching: set[int]) -> Counter[str]:
    """One pass at `now`; `watching` is the households holding subscriptions from the last, updated. Raises
    ShadowsUnavailable."""
    store = services.get(Shadows)
    counts: Counter[str] = Counter()
    active = await store.households()
    for household in sorted(set(active) | watching):
        types: dict[str, Recorder] = _recorders(household) if household in active else {}
        try:
            await services.get(HeldStates).events(household, types)
        except (HouseUnavailable, HomesUnavailable):
            counts["unreachable"] += 1
            continue
        if household in active:
            watching.add(household)
        else:
            watching.discard(household)
    counts["households"] = len(active)
    for run_ in await store.due(now):
        counts["ended" if await _end(run_, now) else "retry"] += 1
    counts["pruned"] = await store.prune(now)
    if counts["ended"] or counts["retry"] or counts["pruned"] or counts["unreachable"]:
        logs.info(log, "workshop.shadow_tick", **{k: counts[k] for k in ("households", "ended", "retry", "pruned",
                                                                         "unreachable")})
    return counts


def _recorders(household_id: int) -> dict[str, Recorder]:
    async def would(event: HouseEvent) -> None:
        data = event.data
        bench, piece = data.get("bench"), data.get("piece")
        if type(bench) is int and type(piece) is int and await services.get(Shadows).would(
                household_id, bench, piece, event.at, event.context):
            logs.info(log, "workshop.shadow_firing", bench=bench, piece=piece, kind="would")

    async def did(event: HouseEvent) -> None:
        entity = event.data.get("entity_id")
        if isinstance(entity, str) and await services.get(Shadows).did(household_id, entity, event.at, event.context):
            logs.info(log, "workshop.shadow_firing", kind="did")

    return {shadow.EVENT: would, TRIGGERED: did}


async def _end(run_: NewShadow, now: datetime) -> bool:
    """End the run: Undo its Install as its person, and when that cannot take the shadow out of the house, delete the
    shadow directly. False, the run still running, when the house could not be written to."""
    owner = Owner(run_.household_id, run_.person_id)
    try:
        applied = await services.get(Workshop).apply(owner, run_.bench_id, Undo(By(run_.person_id), run_.install_seq))
        record = await carry_out(owner, run_.bench_id, applied)
        if record is not None and record.ending == "done":
            await services.get(Shadows).end(run_.bench_id, run_.install_seq, now)
            return True
    except (WorkshopError, InstallsUnavailable, HomesUnavailable):
        pass
    try:
        await remove(await house_of(run_.household_id), shadow.id_for(automation_id_for(run_.bench_id, run_.piece_id)))
    except (HouseUnavailable, HouseRejected, HomesUnavailable):
        logs.warning(log, "workshop.shadow_remove_failed", bench=run_.bench_id, seq=run_.install_seq)
        return False
    await services.get(Shadows).end(run_.bench_id, run_.install_seq, now)
    return True


async def remove(house: House, automation_id: str) -> bool:
    """Delete shadow `automation_id` from the house; False when it has none. Raises ValueError, deleting nothing, for an
    id that is not a shadow's, and HouseUnavailable."""
    if not shadow.is_id(automation_id):
        raise ValueError("only a shadow's id is deleted")
    return await house.delete_config("automation", automation_id)
