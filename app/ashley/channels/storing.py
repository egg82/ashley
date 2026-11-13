"""What of her reply is stored and queued with it (`respond` step 7): the turn answering a person's, and what goes out
through the `Outbox` in the same transaction."""

import logging

from .. import logs
from ..conversations.model import NewTurn, Receipts
from ..inference.reply import Reply
from ..people.model import Person
from . import aloud, history, to_phone, unprompted
from .model import Inbound, Outbound
from .outbox import Pushed
from .push.later import thread
from .render import delivered, render

log = logging.getLogger("ashley.channels")


def stored(reply: Reply, inbound: Inbound, speaker: Person | None, phone: int | None, conversation_id: int,
           said_id: int, queued: tuple[Pushed, ...] = (),
           receipts: Receipts | None = None) -> tuple[NewTurn, tuple[Pushed, ...]]:
    """Her turn answering the person turn `said_id` and what is queued with it: `queued` and the copy to the phone, in
    which case the turn holds `text`, private to the speaker; else the field the medium delivers, heard as the
    channel's turns are; on an unprompted turn that does not go out, `unprompted.QUIET`. The turn carries `receipts`
    (what code shows beside her words), and on a spoken channel nothing of them is said: they go to the speaker's phone,
    in the copy when she chose to send one, else on their own (`receipt_push`). The turn carries `spoken` when the
    message offered her to answer aloud and she did (`aloud.spoken`)."""
    heard = reply
    reply = unprompted.as_said(reply, inbound)
    copy = to_phone.copy(reply, phone, inbound.household_id, conversation_id, receipts)
    alone = receipt_push(receipts, inbound, phone, conversation_id, silent=reply is not heard) if copy is None else None
    queued = (*queued, *((alone,) if alone is not None else ()))
    voice = aloud.spoken(reply, inbound, conversation_id)
    if inbound.unprompted:
        logs.info(log, "wake.outcome", conversation=conversation_id,
                  outcome="phone" if copy is not None else "thread" if reply is heard else "silent")
    if copy is not None:
        said = NewTurn("ashley", reply.text, None, *history.heard(inbound, speaker, to_phone=True), answers=said_id,
                       spoken=voice, receipts=receipts)
        return said, (*queued, copy)
    return NewTurn("ashley", delivered(reply, inbound.medium), None, *history.heard(inbound, speaker),
                   answers=said_id, spoken=voice, receipts=receipts), queued


def receipt_push(receipts: Receipts | None, inbound: Inbound, phone: int | None,
                 conversation_id: int, silent: bool = False) -> Pushed | None:
    """The receipts alone, queued for the phone of `phone` (`to_phone.reachable`), when the turn is on a spoken channel,
    which says none of them, or `silent`: she was woken and kept it to herself, so no reply carries them: an `Outbound`
    with no body. None when there are none (the choice rows of `Receipts.facts` are the bench page's alone) or the
    receipts go out with her reply; and
    when the speaker has no phone to reach it is logged `receipts.unshown` (conversation, medium, done, held) and the
    stored turn is where they are kept."""
    if receipts is None or not (receipts.done or receipts.held) or not (inbound.medium == "spoken" or (silent and inbound.unprompted)):
        return None
    if phone is None:
        logs.info(log, "receipts.unshown", conversation=conversation_id, medium=inbound.medium, done=len(receipts.done),
                  held=len(receipts.held))
        return None
    return Pushed(inbound.household_id, thread(phone), Outbound(conversation_id, "text", "", receipts=receipts))


async def pushed(reply: Reply, inbound: Inbound, conversation_id: int, receipts: Receipts | None = None,
                 said_id: int | None = None) -> tuple[Pushed, ...]:
    """Her answer as queued for the thread, when it goes out after the response through the `Outbox`: never on an
    unprompted turn that `Initiative` keeps quiet. `said_id` is the person turn it answers."""
    if inbound.later_by != "outbox" or not unprompted.decided(reply, inbound, conversation_id):
        return ()
    body = await render(reply, inbound.medium, inbound.household_id)
    return (Pushed(inbound.household_id, inbound.thread, Outbound(
        conversation_id, inbound.medium, body, receipts=receipts), said_id),)
