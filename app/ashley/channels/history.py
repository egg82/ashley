"""Who could hear each turn she stores, and which earlier turns one reply carries (`respond` steps 2 and 4): the speaker's
latest turns across conversations and older ones matching the message, each passing who may hear it, by
`Conversations.carried` with the budgets in `turns.json`."""

from .. import services
from ..conversations.conversations import Conversations
from ..conversations.model import Carried, Hearer, Heard, Turn
from ..people.model import Person
from .limits import Limits
from .model import Inbound


def heard(inbound: Inbound, speaker: Person | None, to_phone: bool = False) -> tuple[Heard, int | None]:
    """Who could hear a turn said on `inbound`'s channel, and whose it is when private: on an owner-only channel, or
    sent to the speaker's phone, it is private to the speaker (to no one when unknown); otherwise the household could
    hear it."""
    if inbound.audience == "owner" or to_phone:
        return "private", None if speaker is None else speaker.id
    return "shared", None


def hearer(inbound: Inbound, speaker: Person | None) -> Hearer:
    """Who will hear the reply: the speaker, alone only on an owner-only channel, as recall's `Asker` is built."""
    return Hearer(inbound.household_id, None if speaker is None else speaker.id, inbound.audience == "owner")


async def carried(inbound: Inbound, speaker: Person | None, conversation_id: int, said: Turn,
                  limits: Limits) -> Carried:
    """The earlier turns a reply to `said` carries. Raises ConversationsUnavailable."""
    return await services.get(Conversations).carried(hearer(inbound, speaker), conversation_id, said.id, inbound.text,
                                                     limits.recent_turns, limits.relevant_turns)
