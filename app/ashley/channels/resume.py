"""Turns whose runner stopped, finished by another (`docs/decisions.md`, "Work in flight survives its pod"). `run` is
the `inflight` singleton: every `poll_s` it `sweep`s, claiming the work whose claim ran out (`InFlight.orphaned`) and
running each from its checkpoint to her stored turn, which open screens learn of through Live, and which is queued in
the `Outbox` for the thread in the same transaction on a channel that takes its later replies from there. A resumed
turn never holds, and its deadline counts the work done in its current window (`Checkpoint.worked_s`), never the time it waited to be resumed. Tunables are data (`inflight_config`).

Logs `respond.resumed` with the conversation, the person turn, attempts and age_ms when a turn is taken up, and with
`acting=true` and no timings when what is left is a memory act (`Checkpoint.acting`);
`respond.done` with `resumed=true`, the conversation, kind, medium, tool rounds, tool calls, tools_required, `tainted`, `changes`, `closed`, `answers` and
duration_ms when it is answered; `respond.failed` with `resumed=true` and the reason (`gave_up` past `max_attempts`,
`bad_checkpoint`, or as `respond` gives it) when it is not, and nothing is stored; `respond.memory_act_interrupted` with
the conversation, the person turn and the action when her stored turn's memory act was cut off while it ran, which is
not begun again; `inflight.unavailable` once per run of
sweeps that could not reach the database. Never text."""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Mapping

from .. import logs, services
from ..conversations.inflight import InFlight, InFlightUnavailable, Orphan
from ..inference.model import SystemPrompt
from ..inference.reply import Reply
from ..live.events import FailedWhy
from ..people.model import Person
from ..people.people import People
from . import agree, answering, checkpoint, continued, ending, keep, left, settled, tool_loop
from .checkpoint import Acting, Checkpoint
from .inflight import Saved, dropped
from .inflight_config import CONFIG as CONFIG, Config as Config
from .landing import Landing
from .live_turn import Showing
from .respond import LIMITS, failed_later, kept, record
from .storing import pushed, stored

log = logging.getLogger("ashley.channels")

NAME = "inflight"


async def run(sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> None:
    """Sweep every `poll_s` until cancelled."""
    failing = False
    while True:
        try:
            await sweep()
        except InFlightUnavailable:
            if not failing:
                logs.warning(log, "inflight.unavailable")
            failing = True
        else:
            failing = False
        await sleep(CONFIG.poll_s)


async def sweep() -> int:
    """Claim the work whose runner stopped and finish each, together; how many were claimed. Raises
    InFlightUnavailable when none could be claimed."""
    orphans = await services.get(InFlight).orphaned(CONFIG.batch)
    await asyncio.gather(*(_resumed(o) for o in orphans))
    return len(orphans)


async def _resumed(orphan: Orphan) -> None:
    saved: Checkpoint | None = None
    given_up = orphan.attempts > CONFIG.max_attempts
    try:
        saved = checkpoint.loads(orphan.checkpoint)
    except (ValueError, KeyError, TypeError):
        pass
    if saved is not None and saved.acting is not None:
        await _acted(Saved(orphan.claim, saved), saved.acting, given_up)
        return
    if saved is None or given_up:
        gone = await dropped(orphan.claim)
        reason = "gave_up" if given_up else "bad_checkpoint"
        logs.warning(log, "respond.failed", resumed=True, reason=reason, later=True)
        ending.record(reason, orphan.claim.conversation_id, "failed_shown" if gone else "kept")
        addressed = checkpoint.addressed(orphan.checkpoint)
        if gone and addressed is not None:
            _ended(Showing(*addressed), "unavailable")
        return
    logs.info(log, "respond.resumed", conversation=orphan.claim.conversation_id, said=orphan.claim.said_id,
              attempts=orphan.attempts, age_ms=int(orphan.age_s * 1000))
    if saved.left:
        await left.answer(Saved(orphan.claim, saved))
        return
    if saved.inbound.agree is not None:
        await agree.resume(Saved(orphan.claim, saved))
        return
    await _finished(Saved(orphan.claim, saved))


async def _acted(work: Saved, acting: Acting, given_up: bool) -> None:
    """The memory act her stored turn left: carried out when it never began, else (or past `max_attempts`) the work
    ended unrepeated. Her answer is stored, so nothing is shown failed."""
    saved = work.checkpoint
    logs.info(log, "respond.resumed", conversation=saved.conversation_id, said=saved.said_id, acting=True)
    if acting.started or given_up:
        logs.warning(log, "respond.memory_act_interrupted", conversation=saved.conversation_id, said=saved.said_id,
                     action=acting.act.action)
        await work.drop()
        return
    await work.act(saved.conversation_id, saved.said_id, acting.hers, acting.act, saved.inbound.household_id,
                   saved.speaker_id)


async def _finished(work: Saved) -> None:
    saved = work.checkpoint
    inbound = saved.inbound
    showing = Showing(inbound, saved.turn)
    showing.state("thinking")
    started = time.perf_counter() - saved.worked_s
    try:
        landing = Landing(inbound, (saved.conversation_id, saved.said_id), LIMITS, saved.tainted)
        landing.recording(work)
        catalogue = await tool_loop.offered(landing)
        speaker = await _speaker(saved)

        async def arrive(system: Mapping[str, SystemPrompt]) -> tool_loop.Arrived | None:
            return await continued.arrived(landing, speaker, saved.said_id, showing, work, system)

        specs = catalogue.specs if catalogue is not None else ()
        answer = await work.guarded(tool_loop.resumed(
            saved.to_resume(), landing.kind, saved.system, specs, landing.limits, saved.conversation_id, landing,
            inbound.holds, started, steps=work, arrive=arrive, medium=inbound.medium, escalation=landing.escalation))
        answer = await answering.stored(work, answer, lambda r: _stored(work, r, showing, landing), answering.Going(
            landing, saved.conversation_id, saved.system, specs, inbound.holds, started, arrive, inbound.medium,
            landing.escalation))
    except Exception as e:
        survives = await settled.settle(work, e, failed_later(e, started, resumed=True), settled.Ended(
            inbound, saved.conversation_id, saved.said_id, await _speaker(saved), showing), CONFIG.unavailable_retry_s)
        if not survives:
            showing.state("idle")
        return
    logs.info(log, "respond.done", resumed=True, conversation=saved.conversation_id, kind=inbound.kind,
              medium=inbound.medium, tool_rounds=answer.rounds, tool_calls=answer.calls,
              tools_required=answer.required, **answer.closing(), tainted=work.taint or "none", held=landing.held,
              duration_ms=int((time.perf_counter() - started) * 1000))
    showing.state("idle")


def _ended(showing: Showing, why: FailedWhy) -> None:
    """The turn ended with no reply and its work is gone: its person is told as the request would have told them,
    and she is idle."""
    showing.failed(why)
    showing.state("idle")


async def _stored(work: Saved, reply: Reply, showing: Showing, landing: Landing) -> None:
    saved = work.checkpoint
    act = keep.act(reply, saved.inbound, saved.offered, saved.conversation_id)
    speaker = await _speaker(saved)
    said, queued = stored(reply, saved.inbound, speaker, saved.phone, saved.conversation_id, saved.said_id,
                          await pushed(reply, saved.inbound, saved.conversation_id, landing.receipts), landing.receipts)
    said = work.answering(said)
    said = await continued.said_on_bench(landing.inbound, speaker, saved.said_id, said, saved.conversation_id,
                                         showing)
    hers = await record(work, saved.conversation_id, said, showing, queued, act)
    kept(work, act, saved.inbound, saved.conversation_id, saved.said_id, hers, saved.speaker_id)


async def _speaker(saved: Checkpoint) -> Person | None:
    """The speaker the turn began with, as the household reads now; None when unknown or gone."""
    if saved.speaker_id is None:
        return None
    household = await services.get(People).household(saved.inbound.household_id)
    people = {} if household is None else {p.id: p for p in household.people}
    return people.get(saved.speaker_id)

