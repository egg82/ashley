"""A person's Undo of something she did on her own for them (`POST /api/work/actions/{id}/undo`, `decisions.md`, "What
she did on her own is one record"): the `outside_actions` row's undo, claimed so it is taken once, carried out through
her own tool for that change (`ashley.tools.undo_carry`), and kept on the row as how it ended. A row that is not theirs is
`UndoNotFound`; one with no undo, or whose undo was already taken, is refused before anything is done. What would be
done is settled by the tool's own checks, never here: a delete is proposed for their yes as shipped, in a turn stored
on their web thread as the household's line (`author` `household`, never words of theirs), so their yes after it there
is what `house_confirm` answers.

The claim's lapse and the turn a delete's undo stores are data, `undo.json` beside this module. Logs one `undo.done`
line per request with the action, the undo's kind and the outcome; never a ref, a summary or a list."""

import json
import logging
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

from .. import logs, services
from ..conversations.conversations import ConversationClosed, ConversationsUnavailable
from ..people.people import PeopleUnavailable
from ..senses.outside_record import OutsideRecord, OutsideRecordUnavailable, Recorded
from ..tools.undo_carry import Carried, Opened, UndoFailed, UndoUnavailable, carry
from . import person_turn, speaker
from .model import Inbound

log = logging.getLogger("ashley.channels")
FILE = Path(__file__).with_name("undo.json")
Refusal = Literal["no_undo", "already_undone", "failed"]


@dataclass(frozen=True)
class UndoConfig:
    """How long a claim on an undo holds before another request may take it (`claim_s`), and the words a delete's undo
    stores as the household's line before the action's summary (`turn`)."""

    claim_s: float
    turn: str


def load() -> UndoConfig:
    """`undo.json`. Raises ValueError unless it is exactly a positive `claim_s` and a non-empty `turn`."""
    raw = json.loads(FILE.read_text())
    if set(raw) != {"claim_s", "turn"}:
        raise ValueError("undo.json has exactly claim_s and turn")
    claim_s: object = raw["claim_s"]
    turn: object = raw["turn"]
    if isinstance(claim_s, bool) or not isinstance(claim_s, int | float) or claim_s <= 0:
        raise ValueError("claim_s: expected a positive number")
    if not isinstance(turn, str) or not turn.strip():
        raise ValueError("turn: expected text")
    return UndoConfig(float(claim_s), turn)


CONFIG = load()


class UndoNotFound(Exception):
    """No action of the person's in this household has that id."""


class UndoRefused(Exception):
    """The undo was not carried out; `reason` says why: `no_undo` (the action has no inverse), `already_undone` (its
    undo was taken, or is being taken now), `failed` (the tool refused it or could not make it)."""

    def __init__(self, reason: Refusal) -> None:
        super().__init__(reason)
        self.reason: Refusal = reason


async def undo(inbound: Inbound, action_id: int) -> Carried:
    """The undo of the action `action_id` made for `inbound`'s speaker, carried out on their web thread `inbound`.
    Raises UndoNotFound, UndoRefused, UndoUnavailable (nothing was done, and the Undo is offered again)."""
    if inbound.speaker_id is None:
        raise ValueError("an undo is a person's own")
    kind: str | None = None
    outcome = "unavailable"
    try:
        found = await _found(inbound.household_id, inbound.speaker_id, action_id)
        kind = None if found.action.undo is None else found.action.undo.kind
        done = await _taken(inbound, found)
        outcome = done.outcome
        return done
    except UndoNotFound:
        outcome = "not_found"
        raise
    except UndoRefused as e:
        outcome = e.reason
        raise
    finally:
        logs.info(log, "undo.done", action=action_id, person=inbound.speaker_id, kind=kind, outcome=outcome)


async def _found(household_id: int, person_id: int, action_id: int) -> Recorded:
    try:
        found = await services.get(OutsideRecord).one(household_id, person_id, action_id)
    except OutsideRecordUnavailable as e:
        raise UndoUnavailable("the outside record is unavailable") from e
    if found is None:
        raise UndoNotFound()
    if found.action.undo is None:
        raise UndoRefused("no_undo")
    return found


async def _taken(inbound: Inbound, found: Recorded) -> Carried:
    """The claimed undo carried out and settled; on failure the claim is given up, so nothing is recorded as undone."""
    undo, record = found.action.undo, services.get(OutsideRecord)
    if undo is None or inbound.speaker_id is None:
        raise UndoRefused("no_undo")
    try:
        if not await record.claim_undo(inbound.household_id, inbound.speaker_id, found.id, CONFIG.claim_s):
            raise UndoRefused("already_undone")
    except OutsideRecordUnavailable as e:
        raise UndoUnavailable("the outside record is unavailable") from e
    try:
        done = await carry(undo, inbound.household_id, inbound.speaker_id, _opener(inbound, found))
    except UndoFailed as e:
        await _release(found.id)
        raise UndoRefused("failed") from e
    except (UndoUnavailable, PeopleUnavailable, ConversationsUnavailable, ConversationClosed) as e:
        await _release(found.id)
        raise UndoUnavailable(type(e).__name__) from e
    try:
        await record.settle_undo(found.id, done.outcome)
    except OutsideRecordUnavailable:
        logs.warning(log, "undo.unsettled", action=found.id, outcome=done.outcome)
    return done


def _opener(inbound: Inbound, found: Recorded) -> Opened:
    """Stores the turn a delete's undo is proposed in, on the person's web thread and private to them: the household's
    line (`author` `household`, no speaker), `undo.json`'s `turn` and the action's summary, which code wrote. The
    proposal is still the person's (`made_by`), so only a later turn of theirs agrees to it."""
    async def opened() -> tuple[int, int]:
        who = await speaker.who(inbound)
        text = f"{CONFIG.turn} {found.action.summary}"
        conversation, said = await person_turn.stored(replace(inbound, text=text, author="household"), who.speaker)
        return conversation.id, said.id
    return opened


async def _release(action_id: int) -> None:
    try:
        await services.get(OutsideRecord).settle_undo(action_id, None)
    except OutsideRecordUnavailable:
        logs.warning(log, "undo.unreleased", action=action_id)
