"""Carrying an accepted Install, or the Undo of one, out on the owner's household's house
(`home_assistant.homes.automations_of`), after the command is logged. Each is recorded (`installs.Installs`) before
its first write to Home Assistant and again when it ends, so a pod that stops part way leaves an accepted command
with no record (nothing was written) or a record with no ending (it may have written some of it); neither is ever
carried out again.

An install reads what HA holds under its id and whether the automation it turns off is on, records that, writes the
piece's config (never over an automation under that id that no earlier install of the piece wrote: another database's
bench may share the id), turns it on or off as proposed, then turns the old one off. Its undo puts the house back from that
record: a fresh install is deleted, an update has the config and on/off state it had before written back, and the old
automation is turned on again only if the install found it on. An install that wrote nothing has nothing to undo."""

import logging
import time
from dataclasses import replace

from .. import logs, services
from ..home_assistant.automations import AutomationRejected, Automations, AutomationsUnavailable
from ..home_assistant.homes import automations_of
from ..live.events import BenchChanged, Shown
from ..live.live import Live
from . import automation_config
from .commands import Installed, Uninstalled
from .installs import Before, Ending, InstallRecord, Installs, InstallsUnavailable, NewInstall
from .model import Owner
from .workshop import Applied, Workshop, WorkshopError

log = logging.getLogger("ashley.workshop")
UNREACHABLE = "Home Assistant could not be reached; nothing was changed"
CHANGED = "the piece changed before it reached the house; nothing was written"
NO_ENTITY = "written, but Home Assistant did not show it in time, so it was not turned on or off; check it there"
TAKEN = ("Home Assistant already has an automation under this piece's id that this bench never installed; nothing "
         "was written")
NOTHING = "the install wrote nothing to the house, so there was nothing to take back"
PART_WAY = "Home Assistant stopped answering part way ({step}); some of it may have changed, so check it there"


def automation_id_for(bench_id: int, piece_id: int) -> str:
    """The id a piece is installed under in Home Assistant, the same for every install of it."""
    return f"ashley_bench_{bench_id}_piece_{piece_id}"


async def carry_out(owner: Owner, bench_id: int, applied: Applied) -> InstallRecord | None:
    """When `applied` is an accepted Install or the Undo of one, carry it out on the house, tell the owner's screens
    the bench changed (`BenchChanged`), and return its record as it ended; None for any other command, or when the
    record could not be written (then nothing was written to the house) or the bench could not be read back. A command
    already carried out, or begun, is never carried out again: its record is returned as it stands. Never raises: what
    Home Assistant did is in the record's ending."""
    effect = applied.effect
    if not isinstance(effect, (Installed, Uninstalled)):
        return None
    started = time.monotonic()
    try:
        if isinstance(effect, Installed):
            ending = await _install(owner, bench_id, applied.seq, effect)
        else:
            ending = await _uninstall(owner, bench_id, applied.seq, effect)
    except (InstallsUnavailable, WorkshopError):
        logs.warning(log, "workshop.install", bench=bench_id, seq=applied.seq, piece=effect.piece_id,
                     outcome="unrecorded", ms=_ms(started))
        return None
    except ValueError:
        ending = "already"
    logs.info(log, "workshop.install", bench=bench_id, seq=applied.seq, piece=effect.piece_id,
              action="install" if isinstance(effect, Installed) else "uninstall", outcome=ending, ms=_ms(started))
    services.get(Live).publish(BenchChanged(Shown(owner.household_id, owner.person_id), bench_id, applied.seq))
    try:
        return await services.get(Installs).of(owner.household_id, bench_id, applied.seq)
    except InstallsUnavailable:
        return None


def _ms(started: float) -> int:
    return round((time.monotonic() - started) * 1000)


def _new(owner: Owner, bench_id: int, seq: int, effect: Installed, before: Before | None, touched: bool) -> NewInstall:
    return NewInstall(owner.household_id, bench_id, seq, effect.piece_id, "install", effect.automation_id,
                      effect.enabled, effect.turn_off, before, touched)


async def _untouched(install: NewInstall, note: str) -> Ending:
    """Record an install or uninstall that could not begin, as started and failed at once."""
    await services.get(Installs).start(install)
    await services.get(Installs).finish(install.bench_id, install.seq, "failed", note)
    return "failed"


async def _install(owner: Owner, bench_id: int, seq: int, effect: Installed) -> Ending:
    view = await services.get(Workshop).read(owner, bench_id)
    piece = next((p for p in view.pieces if p.id == effect.piece_id and p.version == effect.version), None)
    config = None if piece is None else automation_config.config_of(piece.text.body)
    if config is None:
        return await _untouched(_new(owner, bench_id, seq, effect, None, False), CHANGED)
    try:
        house = await automations_of(owner.household_id)
        before = await _before(house, effect)
    except AutomationsUnavailable:
        return await _untouched(_new(owner, bench_id, seq, effect, None, False), UNREACHABLE)
    if before.config is not None and not await _installed_before(owner, bench_id, effect.piece_id):
        return await _untouched(_new(owner, bench_id, seq, effect, None, False), TAKEN)
    await services.get(Installs).start(_new(owner, bench_id, seq, effect, before, True))
    ending, note = await _write(house, effect, config, before)
    await services.get(Installs).finish(bench_id, seq, ending, note)
    return ending


async def _installed_before(owner: Owner, bench_id: int, piece_id: int) -> bool:
    """Whether an earlier install or uninstall of the piece may have written to the house, so what HA holds under its
    id is ours."""
    return await services.get(Installs).wrote_before(owner.household_id, bench_id, piece_id)


async def _before(house: Automations, effect: Installed) -> Before:
    config = await house.config(effect.automation_id)
    listed = await house.listed()
    own = next((a for a in listed if a.automation_id == effect.automation_id), None)
    old = next((a for a in listed if a.entity_id == effect.turn_off), None) if effect.turn_off else None
    return Before(config, None if config is None or own is None else own.enabled, None if old is None else old.enabled)


async def _write(house: Automations, effect: Installed, config: dict[str, object],
                 before: Before) -> tuple[Ending, str | None]:
    step = "write"
    try:
        entity = await house.write(effect.automation_id, config)
        if entity is None:
            return "failed", NO_ENTITY
        step = "turn on" if effect.enabled else "turn off"
        await house.set_enabled(entity, effect.enabled)
        if effect.turn_off is not None and before.turn_off_was_on:
            step = "turn off the old automation"
            await house.set_enabled(effect.turn_off, False)
    except AutomationRejected as e:
        return "refused", e.message
    except AutomationsUnavailable:
        return "failed", PART_WAY.format(step=step)
    return "done", None


async def _uninstall(owner: Owner, bench_id: int, seq: int, effect: Uninstalled) -> Ending:
    installed = await services.get(Installs).of(owner.household_id, bench_id, effect.install)
    turn_off = None if installed is None else installed.started.turn_off
    new = NewInstall(owner.household_id, bench_id, seq, effect.piece_id, "uninstall", effect.automation_id, None,
                     turn_off, None, True)
    if installed is None or not installed.started.touched or installed.ending == "refused":
        await services.get(Installs).start(replace(new, touched=False))
        await services.get(Installs).finish(bench_id, seq, "done", NOTHING)
        return "done"
    await services.get(Installs).start(new)
    ending, note = await _take_back(await automations_of(owner.household_id), effect, installed)
    await services.get(Installs).finish(bench_id, seq, ending, note)
    return ending


async def _take_back(house: Automations, effect: Uninstalled, installed: InstallRecord) -> tuple[Ending, str | None]:
    before = installed.started.before or Before(None, None, None)
    step = "delete"
    try:
        if before.config is None:
            await house.delete(effect.automation_id)
        else:
            step = "write back"
            entity = await house.write(effect.automation_id, before.config)
            if entity is not None and before.enabled is not None:
                await house.set_enabled(entity, before.enabled)
        if installed.started.turn_off is not None and before.turn_off_was_on:
            step = "turn the old automation back on"
            await house.set_enabled(installed.started.turn_off, True)
    except AutomationRejected as e:
        return "refused", e.message
    except AutomationsUnavailable:
        return "failed", PART_WAY.format(step=step)
    return "done", None
