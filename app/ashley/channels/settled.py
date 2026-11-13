"""How a turn ends after its first line went out without its answer, when its model could not be reached or the answer
could not be stored: the work is kept for another runner when it can be, and the person is never left with nothing.

A model that cannot be reached (`InferenceUnavailable`) on work that outlives its runner (`Work.retries`) is told once
as her turn, `unsaid.unreachable`, marked `follows`, stored in the bench's talk when the page moved the turn to one (as her held line is), and queued for the thread like any reply (on a paged channel,
`Inbound.paged`, no turn: the page is shown `retrying` instead, `Showing.failed`); the work is then held for
`unavailable_retry_s` (`inflight_config`) and the resume sweep takes it again, counted as an attempt, until
`max_attempts`. Any other ending deletes the work when it can: the person's screens are told it failed. Work that cannot
be deleted (the database is out of reach) survives, and the sweep finishes it. Each ending is logged `respond.ended`
(`ending.record`)."""

import logging
from dataclasses import dataclass

from .. import logs, services
from ..conversations.conversations import ConversationError
from ..conversations.inflight import ClaimLost, InFlightError, InFlightUnavailable
from ..conversations.model import NewTurn
from ..inference.inference import InferenceRefused, InferenceUnavailable
from ..live.events import FailedWhy
from ..people.model import Person
from ..workshop.model import thread_of
from . import continued, ending, history, storing, unsaid
from .inflight import Unstored, Work
from .live_turn import Showing
from .model import Inbound
from .outbox import Outbox, OutboxError, OutboxUnavailable
from .render import delivered

log = logging.getLogger("ashley.channels")

# What ends a turn after its first reply went out, and the reason `respond.failed` gives for it.
LATER: tuple[tuple[type[Exception], str], ...] = (
    (InferenceRefused, "refused"),
    (InferenceUnavailable, "inference_unavailable"),
    (OutboxUnavailable, "outbox_unavailable"),
    (InFlightUnavailable, "inflight_unavailable"),
    (ClaimLost, "claim_lost"),
    (Unstored, "unstorable"),
    (unsaid.Unworded, "unworded"),
)


@dataclass(frozen=True)
class Ended:
    """The turn that ended: its message, where it was said, who is speaking and the screens it is shown on."""

    inbound: Inbound
    conversation_id: int
    said_id: int
    speaker: Person | None
    showing: Showing


async def settle(work: Work, error: Exception, reason: str | None, turn: Ended, retry_s: float) -> bool:
    """The turn that ended on `error` (`reason`, as `respond.failed` gave it) settled; whether its work survives, so
    that the runner that finishes it ends her state. Never raises."""
    why = reason or "error"
    if isinstance(error, InferenceUnavailable) and work.retries:
        return await _kept(work, why, turn, retry_s)
    if isinstance(error, ClaimLost):
        ending.record(why, turn.conversation_id, "other_runner")
        return True
    gone = await work.drop()
    ending.record(why, turn.conversation_id, "failed_shown" if gone else "kept")
    if gone:
        turn.showing.failed(_why(error))
    return not gone


def _why(error: Exception) -> FailedWhy:
    if isinstance(error, InferenceRefused):
        return "refused"
    return error.why if isinstance(error, unsaid.Unworded) else "unavailable"


async def _kept(work: Work, reason: str, turn: Ended, retry_s: float) -> bool:
    told = not work.unreachable_told and not turn.inbound.paged
    try:
        if turn.inbound.paged:
            turn.showing.failed("retrying")
        elif told:
            await _tell(work, turn)
        await work.defer(retry_s)
    except ClaimLost:
        ending.record(reason, turn.conversation_id, "other_runner")
        return True
    except InFlightError as e:
        logs.warning(log, "respond.defer_failed", conversation=turn.conversation_id, error=type(e).__name__)
    ending.record(reason, turn.conversation_id, "told_and_kept" if told else "kept")
    return True


async def _tell(work: Work, turn: Ended) -> None:
    """She could not reach her thinking, said once: stored under the work's claim, in the bench's talk when the turn's page
    is on a bench (as her held line is), queued for the thread, then noted in the checkpoint."""
    inbound, reply = turn.inbound, unsaid.unreachable()
    said = NewTurn("ashley", delivered(reply, inbound.medium), None, *history.heard(inbound, turn.speaker),
                   follows=True, answers=turn.said_id)
    where, talk = turn.conversation_id, None
    on_bench = await continued.held_on_bench(inbound, turn.speaker, turn.said_id, said, turn.showing)
    if on_bench is not None and inbound.lands_on is not None:
        where, said = on_bench
        talk = thread_of(inbound.lands_on)
    try:
        await work.say(where, said)
    except (ConversationError, ValueError):
        logs.error(log, "respond.turn_unrecorded", exc=True, conversation=where)
    else:
        turn.showing.stored(talk)
    for p in await storing.pushed(reply, inbound, turn.conversation_id):
        try:
            await services.get(Outbox).add(p.household_id, p.thread, p.outbound)
        except OutboxError:
            logs.warning(log, "respond.unreachable_unqueued", conversation=turn.conversation_id)
    await work.told_unreachable()
