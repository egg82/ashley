"""Agreeing to a held change by a tap: a person turn that is a command, not a message (`docs/decisions.md`, "A tap
agrees to what was held"). `Inbound.agree` names the proposal; the turn has no text and a null `taint`, so no model writes
the agreement and no model step follows it. It carries out the held calls of that proposal (`tools.outside`,
`carry_out`) and keeps what became of each call on the person's agreeing turn (`Turn.agreed`): a record the page shows
beside it, built from the calls' summaries and never from what they returned. No turn of hers is stored.

Refused with a typed reason, before anything is stored: `gone` (no such proposal is waiting: carried out already, replaced
by a later one, or never held), `expired` (past `proposal_ttl_s`), `not_yours` (held for another person, or in another
household). The turn is checkpointed like any (`InFlight`): a runner that stops partway is succeeded by another that
carries nothing out twice and records an interrupted run, whose calls may or may not have taken effect.

Logs `agree.refused` (proposal, person, reason), `agree.done` (proposal, conversation, person turn, duration_ms) and
`agree.failed` (proposal, error class), each naming the proposal. Never arguments, summaries or results."""

import json
import logging
import time
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Literal

from .. import logs, services
from ..conversations.conversations import ConversationClosed, ConversationsUnavailable
from ..conversations.inflight import ClaimLost, InFlight, InFlightUnavailable
from ..conversations.model import AgreedOutcome
from ..inference.model import ToolCall, ToolResult
from ..people.people import PeopleUnavailable
from ..senses.proposal_payloads import OUTSIDE
from ..senses.proposals import ProposalRefused, Proposals, ProposalsUnavailable, refusal
from ..tools import outside_config
from . import person_turn, speaker
from .checkpoint import Checkpoint, dumps
from .inflight import Saved
from .landing import Landing
from .live_turn import Showing
from .model import Inbound
from .respond import LIMITS
from .tool_loop import Progress

log = logging.getLogger("ashley.channels")
AgreeRefusal = Literal["gone", "expired", "not_yours"]
CALL_ID = "agreed"
_REASONS: dict[str, AgreeRefusal] = {"none": "gone", "same_turn": "gone", "expired": "expired", "not_yours": "not_yours"}


class AgreeError(Exception):
    """Base of what `agree` raises on purpose."""


class AgreeRefused(AgreeError):
    """The proposal cannot be agreed to; `reason` says why."""

    def __init__(self, reason: AgreeRefusal) -> None:
        super().__init__(reason)
        self.reason: AgreeRefusal = reason


class AgreeUnavailable(AgreeError):
    """A system agreeing needs (People, Conversations, Proposals, InFlight) could not be reached. Transient: the
    proposal is still there unless it was already taken."""


@dataclass(frozen=True)
class Agreed:
    """What agreeing did: `outcome`, kept on the agreeing turn in `conversation_id`."""

    conversation_id: int
    outcome: AgreedOutcome


async def agree(inbound: Inbound) -> Agreed:
    """The held calls of proposal `inbound.agree` carried out for `inbound.speaker_id`, the person turn stored in the
    conversation of `inbound.thread` with what became of them. Raises ValueError unless `agree` is set, `text` is empty,
    `speaker_id` is set, `author` is `person` and `taint` is None, AgreeRefused, AgreeUnavailable."""
    proposal_id = _checked(inbound)
    started = time.perf_counter()
    config = outside_config.load()
    try:
        who = await speaker.who(inbound)
        await _open(inbound, proposal_id, config.proposal_ttl_s)
        conversation, said = await person_turn.stored(replace(inbound, text=config.agreed_turn), who.speaker)
        showing = Showing(inbound)
        showing.stored()
        saved = Checkpoint(inbound, conversation.id, said.id, inbound.speaker_id, {}, Progress((), 0, 0), turn=showing.turn)
        work = Saved(await services.get(InFlight).begin(conversation.id, said.id, dumps(saved)), saved)
        outcome = await _finished(work, saved, showing)
    except ProposalRefused as e:
        raise _refused(inbound, _REASONS[e.reason]) from e
    except (PeopleUnavailable, ConversationsUnavailable, ConversationClosed, ProposalsUnavailable, InFlightUnavailable,
            ClaimLost) as e:
        logs.warning(log, "agree.failed", proposal=proposal_id, error=type(e).__name__)
        raise AgreeUnavailable() from e
    logs.info(log, "agree.done", proposal=proposal_id, conversation=conversation.id, turn=said.id, duration_ms=int((time.perf_counter() - started) * 1000))
    return Agreed(conversation.id, outcome)


async def resume(work: Saved) -> None:
    """The agree turn `work` holds finished by the runner that claimed it: calls that already ran are not run again, a run
    interrupted is recorded as one, and the outcome is kept on the person turn. A proposal gone by then ends the work
    with no outcome."""
    saved = work.checkpoint
    showing = Showing(saved.inbound, saved.turn)
    try:
        await _finished(work, saved, showing)
    except ProposalRefused as e:
        logs.warning(log, "agree.refused", proposal=saved.inbound.agree, resumed=True, reason=_REASONS[e.reason])
        await work.drop()
    except ClaimLost:
        return
    except Exception as e:
        logs.warning(log, "agree.failed", proposal=saved.inbound.agree, resumed=True, error=type(e).__name__)


def _checked(inbound: Inbound) -> int:
    if (inbound.agree is None or inbound.text or inbound.speaker_id is None or inbound.author != "person"
            or inbound.taint is not None):
        raise ValueError("an agreement names a proposal, has no text, and is a person's own, untainted turn")
    return inbound.agree


def _refused(inbound: Inbound, reason: AgreeRefusal) -> AgreeRefused:
    logs.info(log, "agree.refused", proposal=inbound.agree, person=inbound.speaker_id, reason=reason)
    return AgreeRefused(reason)


async def _open(inbound: Inbound, proposal_id: int, ttl_s: float) -> None:
    """Raises AgreeRefused unless the proposal waits, was held for this speaker and has not lapsed; ProposalsUnavailable."""
    found = await services.get(Proposals).find(proposal_id, OUTSIDE)
    if found is None:
        raise _refused(inbound, "gone")
    if found.household_id != inbound.household_id or found.made_by != inbound.speaker_id:
        raise _refused(inbound, "not_yours")
    if refusal(found, found.turn_id + 1, datetime.now(UTC), ttl_s) == "expired":
        raise _refused(inbound, "expired")


async def _finished(work: Saved, saved: Checkpoint, showing: Showing) -> AgreedOutcome:
    """What became of the held calls once they are carried out, kept on the person turn through `work` and shown on the
    screens. Raises ProposalRefused when the proposal went before it could be taken, ClaimLost, InFlightUnavailable."""
    outcome = await work.guarded(_outcome(work, saved))
    await work.agreed(outcome)
    showing.stored()
    return outcome


async def _outcome(work: Saved, saved: Checkpoint) -> AgreedOutcome:
    """The outcome saved when the calls already ran, an interrupted one when they began and did not finish, else the
    calls carried out (recorded begun before, and the outcome saved after)."""
    done = saved.progress.done.get(CALL_ID)
    if done is not None:
        return AgreedOutcome.from_json(json.loads(done.content))
    if CALL_ID in saved.started:
        return AgreedOutcome(interrupted=True)
    inbound = saved.inbound
    landing = Landing(inbound, (saved.conversation_id, saved.said_id), LIMITS)
    await work.starting(ToolCall(CALL_ID, "carry_out", {}))
    outcome = AgreedOutcome(await landing.agreed(CALL_ID, _proposal(inbound)))
    await work.ran(ToolResult(CALL_ID, json.dumps(outcome.to_json())))
    return outcome


def _proposal(inbound: Inbound) -> int:
    if inbound.agree is None:
        raise ValueError("not an agreement")
    return inbound.agree


async def waiting(person_id: int, household_id: int) -> tuple[int, int] | None:
    """The proposal `person_id` can agree to now and the turn it was held in, for a page to show Agree under that turn's
    answer; None when none waits, it has lapsed, or the store cannot be read."""
    try:
        found = await services.get(Proposals).pending(person_id, 0, OUTSIDE)
    except ProposalsUnavailable:
        logs.warning(log, "agree.unavailable", where="waiting")
        return None
    if found is None or found.id is None or found.household_id != household_id:
        return None
    if refusal(found, found.turn_id + 1, datetime.now(UTC), outside_config.load().proposal_ttl_s) is not None:
        return None
    return found.id, found.turn_id
