"""Acting on memory now, when her reply sets `Reply.memory` (`docs/decisions.md`, "People see, correct and forget what
she knows of them"). `act` reads the reply into an `Act`; after her turn is stored, `now` carries it out apart from the
reply, which never waits on it. Only in a remembered conversation. What was done is logged, not stored on the turn:
facts are shown in the Memory room.

- `keep` and `correct` run `ashley.memory.remember` over the person's turn and hers; a `correct` also hands the writer
  the facts it names.
- `forget` is done here, not by the writer: each named fact the speaker may see (`Memory.held`, the Memory room's rule)
  is deleted, and only a known speaker forgets.

It ends as `changed` when facts she held were corrected or ended (forgetting included), else `kept` when facts were
added, `known` when none were, `missing` when a `correct` or `forget` matched nothing she held (or nothing the speaker
may forget), `failed` when it could not be done, and the write job then catches the turns at idle.

Logs `respond.memory_acted` with the conversation and turn ids, the action and the outcome; `respond.keep_failed` with
the conversation and turn ids and the kind of failure; `respond.memory_act_unknown_fact`
with the action and the ids she was not shown; `respond.memory_act_refused` with the fact id a forget skipped. Never
text."""

import logging
from dataclasses import dataclass
from typing import Literal

from .. import logs, services
from ..conversations.conversations import ConversationError, Conversations
from ..inference.reply import Reply
from ..memory.memory import Memory, MemoryUnavailable
from ..memory.remember import Remembered, RememberRefused, RememberUnavailable, remember
from ..people.people import PeopleUnavailable
from .model import Inbound

log = logging.getLogger("ashley.channels")

Outcome = Literal["kept", "changed", "known", "missing", "failed"]

_FAILURES = (ConversationError, MemoryUnavailable, PeopleUnavailable, RememberRefused, RememberUnavailable, ValueError)


@dataclass(frozen=True)
class Act:
    """What her reply asks of memory, `facts` only the ids she was shown (always empty for `keep`)."""

    action: Literal["keep", "correct", "forget"]
    facts: tuple[int, ...]


def act(reply: Reply, inbound: Inbound, offered: frozenset[int], conversation_id: int) -> Act | None:
    """The act `reply` asks for in a conversation that is remembered, None when it asks none. The ids it names outside
    `offered` (what the prompt carried) are dropped and logged."""
    asked = reply.memory
    if asked is None or not inbound.remembers:
        return None
    if asked.action == "keep":
        return Act("keep", ())
    named = tuple(dict.fromkeys(asked.facts))
    shown = tuple(i for i in named if i in offered)
    if len(shown) != len(named):
        logs.warning(log, "respond.memory_act_unknown_fact", conversation=conversation_id, action=asked.action,
                     unknown=",".join(str(i) for i in named if i not in offered))
    return Act(asked.action, shown)


def _outcome(done: Remembered) -> Outcome:
    if done.ended or done.replaced:
        return "changed"
    return "kept" if done.inserted else "known"


async def _forget(conversation_id: int, household_id: int, speaker_id: int | None, facts: tuple[int, ...]) -> Outcome:
    """`changed` when any of `facts` was deleted; one the speaker may not see is refused and logged."""
    if speaker_id is None:
        return "missing"
    memory = services.get(Memory)
    deleted = 0
    for fact in facts:
        if await memory.held(household_id, speaker_id, fact):
            deleted += await memory.forget(household_id, fact, by=speaker_id)
        else:
            logs.warning(log, "respond.memory_act_refused", conversation=conversation_id, fact=fact)
    return "changed" if deleted else "missing"


async def _carry_out(conversation_id: int, turn_id: int, hers: int | None, wanted: Act, household_id: int,
                     speaker_id: int | None) -> Outcome:
    if wanted.action == "forget":
        return await _forget(conversation_id, household_id, speaker_id, wanted.facts)
    if wanted.action == "correct" and not wanted.facts:
        return "missing"
    found = await services.get(Conversations).get(conversation_id)
    if found is None:
        raise ValueError("conversation is gone")
    return _outcome(await remember(found, turn_id, hers, wanted.facts))


async def now(conversation_id: int, turn_id: int, hers: int | None, wanted: Act, household_id: int,
              speaker_id: int | None) -> None:
    """Carries out `wanted` for the person's turn `turn_id` of the conversation, `hers` being the turn of hers that
    answered it (None when it was not stored), and logs how it ended."""
    state: Outcome = "failed"
    try:
        state = await _carry_out(conversation_id, turn_id, hers, wanted, household_id, speaker_id)
    except _FAILURES as e:
        logs.warning(log, "respond.keep_failed", conversation=conversation_id, turn=turn_id, reason=type(e).__name__)
    logs.info(log, "respond.memory_acted", conversation=conversation_id, turn=turn_id, action=wanted.action,
              outcome=state)
