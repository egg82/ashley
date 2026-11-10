"""Whether she may answer aloud on the page a person spoke to her from, and how that voice is played (`decisions.md`,
"Spoken to, she decides whether to answer aloud"). A message tagged `Inbound.said_aloud` (the web chat's and the kiosk's
record button) offers it, as a spoken turn offers `to_phone`; the model decides with `Reply.aloud`, and code honours it
only when offered. Her `spoken` is then stored on her turn (`Turn.spoken`) and fetched by the page, which is open: the
tag is the request itself. A page that closes before her answer never fetches it.

Logs `voice.aloud` (conversation, outcome: `said`, `not_offered`) for each reply that sets `aloud`. Never text."""

import logging

from .. import logs, services
from ..conversations.conversations import Conversations, ConversationsUnavailable
from ..inference.inference import Inference, InferenceUnavailable
from ..inference.reply import Reply
from ..inference.speech import Speech
from . import spoken as caps
from .lexicons import Lexicons
from .model import Inbound

log = logging.getLogger("ashley.channels")
VOICE_S = caps.load().voice_s


class AloudUnavailable(Exception):
    """The turn's voice could not be read or no speech route started. Transient."""


def offered(inbound: Inbound) -> bool:
    """Whether this message offers her to answer aloud: it was said aloud on a page, in text. A pure function of the
    inbound, so a turn resumed from its checkpoint sees the offer it was given."""
    return inbound.said_aloud and inbound.medium == "text"


def spoken(reply: Reply, inbound: Inbound, conversation_id: int) -> str | None:
    """`reply.spoken` to store on her turn when she set `Reply.aloud` and the message offered it; None otherwise, and
    when her `spoken` is blank."""
    if not reply.aloud:
        return None
    voice = reply.spoken if offered(inbound) and reply.spoken.strip() else None
    logs.info(log, "voice.aloud", conversation=conversation_id, outcome="not_offered" if voice is None else "said")
    return voice


async def speech_of(household_id: int, thread: str, turn_id: int) -> Speech | None:
    """`Inference.speak` of the turn's `spoken` with the household's pronunciation words, started; None when the turn
    is not on `thread`, has no voice or is past `SpokenLimits.voice_s`. Raises AloudUnavailable."""
    try:
        body = await services.get(Conversations).spoken(household_id, thread, turn_id, VOICE_S)
        if body is None:
            return None
        said = (await services.get(Lexicons).of(household_id)).respell(body)
        return await services.get(Inference).speak("speak", said)
    except (ConversationsUnavailable, InferenceUnavailable) as e:
        raise AloudUnavailable() from e
