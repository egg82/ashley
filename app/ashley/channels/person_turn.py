"""The person's turn of one message (`respond` step 2): stored in the conversation its thread carries."""

import logging

from .. import logs, services
from ..conversations.conversations import ConversationClosed, Conversations, ConversationsUnavailable
from ..conversations.model import Conversation, NewTurn, Turn
from ..people.model import Person
from . import history
from .model import Inbound


log = logging.getLogger("ashley.channels")


async def stored(inbound: Inbound, who: Person | None) -> tuple[Conversation, Turn]:
    """The conversation the thread carries and the person's turn stored in it with its `inbound.attachment`, asking once more
    when it closed between the two. Raises ConversationsUnavailable, or ConversationClosed when it closed again."""
    conversations = services.get(Conversations)
    participants = [who.id] if who is not None else []
    turn = NewTurn(inbound.author, inbound.text, who.id if who is not None and inbound.author == "person" else None,
                   *history.heard(inbound, who), source=inbound.source, attachment=inbound.attachment)
    conversation = await carrying(inbound, participants)
    try:
        said = await conversations.add_turn(conversation.id, turn)
    except ConversationClosed:
        conversation = await carrying(inbound, participants)
        said = await conversations.add_turn(conversation.id, turn)
    if inbound.attachment is not None:
        logs.info(log, "respond.attached", conversation=said.conversation_id, turn=said.id,
                  chars=len(inbound.attachment.text), tainted=inbound.taint == "pasted")
    return await holding(conversation, said), said


async def holding(conversation: Conversation, said: Turn) -> Conversation:
    """The conversation that holds `said`: another than the thread's now when the message was handed in before
    (`Inbound.source`). Raises ConversationsUnavailable."""
    if said.conversation_id is None or said.conversation_id == conversation.id:
        return conversation
    found = await services.get(Conversations).get(said.conversation_id)
    if found is None:
        raise ConversationsUnavailable("the conversation holding the turn is gone")
    return found


async def carrying(inbound: Inbound, participants: list[int]) -> Conversation:
    return await services.get(Conversations).for_thread(
        inbound.household_id, inbound.thread, inbound.kind, participants, remembered=inbound.remembers,
        channel=inbound.channel, place=inbound.place)
