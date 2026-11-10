"""Her reply on a turn nobody is waiting on (`Inbound.unprompted`): whether it goes out is `Initiative`'s to say, unless
the person asked for it earlier (`Inbound.promised`, a reminder), and one that does not is stored as `QUIET`, so no
later turn carries words she never said. Logs `initiative.decided` with the conversation and `speaks`, once per turn
Initiative decides, never the reply."""

import logging

from .. import logs, services
from ..conversations.quiet import QUIET, shown as shown
from ..inference.reply import Reply
from ..initiative.initiative import Initiative
from .model import Inbound

log = logging.getLogger("ashley.channels")


def speaks(reply: Reply, inbound: Inbound) -> bool:
    """Whether `reply` goes out: always on a turn someone asked for, now or earlier, else as `Initiative` decides."""
    return not _initiative_decides(inbound) or services.get(Initiative).speaks(reply)


def _initiative_decides(inbound: Inbound) -> bool:
    return inbound.unprompted and not inbound.promised


def as_said(reply: Reply, inbound: Inbound) -> Reply:
    """`reply` as her turn records it: unchanged when it goes out, else `QUIET` in every field a medium delivers and
    nothing sent to a phone."""
    if speaks(reply, inbound):
        return reply
    return reply.model_copy(update={"spoken": QUIET, "text": QUIET, "to_phone": False})


def decided(reply: Reply, inbound: Inbound, conversation_id: int) -> bool:
    """`speaks`, logged when the turn is unprompted."""
    out = speaks(reply, inbound)
    if _initiative_decides(inbound):
        logs.info(log, "initiative.decided", conversation=conversation_id, speaks=out)
    return out
