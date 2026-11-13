"""Whether her reply goes out. On a turn nobody is waiting on (`Inbound.unprompted`) it is `Initiative`'s to say, from
the reply and the turn's `Inbound.moment`, unless the person asked for it earlier (`Inbound.promised`, a reminder); on
a turn that may have been overheard (`Inbound.overhears`) it is her `Reply.says`. One that does not go out is stored as
`QUIET`, so no later turn carries words she never said. Logs `initiative.decided` with the conversation and `speaks`,
with its plan's score, roll and outcome at a moment, `outcome=remark` with `repeated` on a remark (`Inbound.remark`), and
`outcome=not_greeting` on a turn with neither, once per turn Initiative decides, never the reply."""

import logging

from .. import logs, services
from ..conversations.quiet import QUIET, shown as shown
from ..inference.reply import Reply, Says
from ..initiative.initiative import Initiative
from ..initiative.remark import repeats
from .model import Inbound
from .render import delivered

log = logging.getLogger("ashley.channels")


def speaks(reply: Reply, inbound: Inbound) -> bool:
    """Whether `reply` goes out: on a turn that may have been overheard (`Inbound.overhears`), unless she set `says`
    `none`; else always on a turn someone asked for, now or earlier, and otherwise as `Initiative` decides."""
    if inbound.overhears:
        return reply.says != "none"
    if not _initiative_decides(inbound):
        return True
    if inbound.remark is not None:
        return services.get(Initiative).remark_speaks(reply, delivered(reply, inbound.medium), inbound.remark)
    return services.get(Initiative).speaks(reply, inbound.moment)


def _initiative_decides(inbound: Inbound) -> bool:
    return inbound.unprompted and not inbound.promised


def says(reply: Reply, inbound: Inbound) -> Says:
    """`reply.says` as the turn honours it: `none` when it does not go out (`speaks`), `offer` when she offered on a
    turn that may have been overheard, else `reply`."""
    if not speaks(reply, inbound):
        return "none"
    return "offer" if inbound.overhears and reply.says == "offer" else "reply"


def as_said(reply: Reply, inbound: Inbound) -> Reply:
    """`reply` as her turn records it: unchanged when it goes out, else `QUIET` in every field a medium delivers and
    nothing sent to a phone."""
    if speaks(reply, inbound):
        return reply
    return reply.model_copy(update={"spoken": QUIET, "text": QUIET, "to_phone": False})


def decided(reply: Reply, inbound: Inbound, conversation_id: int) -> bool:
    """`speaks`, logged when the turn is unprompted."""
    out = speaks(reply, inbound)
    if not _initiative_decides(inbound):
        return out
    if inbound.remark is not None:
        logs.info(log, "initiative.decided", conversation=conversation_id, speaks=out, outcome="remark",
                  repeated=repeats(delivered(reply, inbound.medium), inbound.remark))
        return out
    if inbound.moment is None:
        logs.info(log, "initiative.decided", conversation=conversation_id, speaks=out, outcome="not_greeting")
        return out
    plan = services.get(Initiative).planned(inbound.moment)
    logs.info(log, "initiative.decided", conversation=conversation_id, speaks=out, score=plan.score,
              outcome=plan.outcome, roll=plan.roll)
    return out
