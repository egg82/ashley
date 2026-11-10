"""A person's message to a turn already running (`docs/decisions.md`, "A message on a bench steers the running turn").
A thread whose messages steer (`Inbound.steers`) runs one turn at a time: a message stored while another turn of the
conversation has work in flight starts no turn of its own, and the running turn is handed it before its next step as
the speaker's own words, `<name> just said: <text>`, and before it would return its answer.

Logs `respond.steering` with the conversation, the message's turn and the running turns' count when a message is left to
a running turn, and `respond.steered` with the conversation and how many messages a turn took."""

import logging
from collections.abc import Collection

from .. import logs, services
from ..conversations.conversations import Conversations
from ..conversations.inflight import InFlight, InFlightUnavailable
from ..conversations.model import unhanded
from ..inference.model import Message
from ..people.people import People
from .model import Inbound

log = logging.getLogger("ashley.channels")


async def running(inbound: Inbound, conversation_id: int, said_id: int) -> bool:
    """Whether another turn of the conversation is being answered, so the message `said_id` is left to it. False when
    the thread does not steer or the work cannot be read, which starts a turn as before."""
    if not inbound.steers or not inbound.later:
        return False
    try:
        others = (await services.get(InFlight).working(conversation_id)) - {said_id}
    except InFlightUnavailable:
        return False
    if others:
        logs.info(log, "respond.steering", conversation=conversation_id, said=said_id, running=len(others))
    return bool(others)


async def hand(inbound: Inbound, conversation_id: int, said_id: int, handed: Collection[int]) -> list[tuple[int, Message]]:
    """The person turns of the conversation after `said_id` that the turn has not been handed (`unhanded`), oldest
    first, each with its id, as what its speaker just said; anyone's, as `running` leaves anyone's to the turn."""
    found = await services.get(Conversations).get(conversation_id)
    if found is None:
        return []
    fresh = unhanded(found.turns, said_id, handed)
    if not fresh:
        return []
    household = await services.get(People).household(inbound.household_id)
    names: dict[int | None, str] = {} if household is None else {p.id: p.name for p in household.people}
    logs.info(log, "respond.steered", conversation=conversation_id, messages=len(fresh))
    return [(t.id, Message("person", f"{names.get(t.speaker_id, 'They')} just said: {t.text}")) for t in fresh]
