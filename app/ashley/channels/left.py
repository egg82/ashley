"""A person turn left to a turn of its own (`Checkpoint.left`): a message handed to a steering turn that ended without
answering it (`InFlight.drop_leaving`), answered from the start by the runner that claimed its work, as `respond` would
have answered it.

Logs `respond.failed` with `resumed=true` and the reason when it is not answered, as a resumed turn does."""

import time

from .. import services
from ..conversations.conversations import Conversations, ConversationsUnavailable
from ..conversations.model import Conversation, Turn
from ..inference.inference import InferenceRefused
from . import speaker
from .checkpoint import Checkpoint
from .inflight import Saved, Work
from .live_turn import Showing
from .respond import answer_said, failed_later


async def answer(work: Saved) -> None:
    """The turn `work` holds answered, its reply stored as her turn on the thread; its person's screens told it failed
    when it was not and its work is gone."""
    saved = work.checkpoint
    showing = Showing(saved.inbound, saved.turn)
    showing.state("thinking")
    started = time.perf_counter()
    held = False
    try:
        out = await answer_said(saved.inbound, await speaker.who(saved.inbound), *await _said(saved), started,
                                showing, lambda c: _begun(work, c))
        held = out.follows
    except Exception as e:
        failed_later(e, started, resumed=True)
        if await work.drop():
            showing.failed("refused" if isinstance(e, InferenceRefused) else "unavailable")
    finally:
        if not held:
            showing.state("idle")


async def _said(saved: Checkpoint) -> tuple[Conversation, Turn]:
    found = await services.get(Conversations).get(saved.conversation_id)
    said = None if found is None else next((t for t in found.turns if t.id == saved.said_id), None)
    if found is None or said is None:
        raise ConversationsUnavailable("the turn left to answer is gone")
    return found, said


async def _begun(work: Saved, checkpoint: Checkpoint) -> Work:
    await work.begun(checkpoint)
    return work
