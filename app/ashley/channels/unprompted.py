"""Whether her reply goes out. On a turn nobody is waiting on (`Inbound.unprompted`) it is `Initiative`'s to say, from
the reply and the turn's `Inbound.moment`, unless the person asked for it earlier (`Inbound.promised`, a reminder); on
a turn that may have been overheard (`Inbound.overhears`) it is her `Reply.says`. One that does not go out is stored as
`QUIET`, so no later turn carries words she never said. Logs `initiative.decided` with the conversation and `speaks`,
with its plan's score, roll and outcome at a moment, `outcome=remark` with `repeated` on a remark (`Inbound.remark`), and
`outcome=quiet` on a turn for a person in their own quiet hours (`Inbound.quiet`), and `outcome=not_greeting` on a
turn with neither, once per turn Initiative decides, never the reply. A turn kept quiet that is not a remark is also recorded
(`OutsideRecord.quieted`, `decisions/senses.md`, Initiative), with `why` as a code; a record that cannot be written is
logged `initiative.quiet_unrecorded` and the turn goes on."""

import logging
from datetime import UTC, datetime

from .. import logs, services
from ..conversations.quiet import QUIET, shown as shown
from ..inference.reply import Reply, Says
from ..initiative.initiative import Initiative
from ..initiative.moment import Plan
from ..initiative.remark import repeats
from ..senses.outside_record import OutsideRecord, OutsideRecordUnavailable, QuietEntry, Why
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
    return services.get(Initiative).speaks(reply, inbound.moment, inbound.quiet)


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


async def decided(reply: Reply, inbound: Inbound, conversation_id: int) -> bool:
    """`speaks`, logged when the turn is unprompted, and recorded when it is kept quiet."""
    out = speaks(reply, inbound)
    if not _initiative_decides(inbound):
        return out
    if inbound.remark is not None:
        logs.info(log, "initiative.decided", conversation=conversation_id, speaks=out, outcome="remark",
                  repeated=repeats(delivered(reply, inbound.medium), inbound.remark))
        return out
    if inbound.quiet:
        logs.info(log, "initiative.decided", conversation=conversation_id, speaks=out, outcome="quiet")
        return await _kept(out, inbound, conversation_id, "quiet_hours", None)
    if inbound.moment is None:
        logs.info(log, "initiative.decided", conversation=conversation_id, speaks=out, outcome="not_greeting")
        return await _kept(out, inbound, conversation_id, "not_greeting", None)
    plan = services.get(Initiative).planned(inbound.moment)
    logs.info(log, "initiative.decided", conversation=conversation_id, speaks=out, score=plan.score,
              outcome=plan.outcome, roll=plan.roll)
    return await _kept(out, inbound, conversation_id, _why(plan), plan.score)


def _why(plan: Plan) -> Why:
    """Why a turn at a moment with `plan` was kept quiet: the plan's own silence, else her `says`."""
    if plan.outcome != "silent":
        return "said_none"
    return "below_threshold" if plan.roll is None else "rolled_silent"


async def _kept(out: bool, inbound: Inbound, conversation_id: int, why: Why, score: float | None) -> bool:
    """`out`, after recording the turn as kept quiet when it did not go out."""
    if out:
        return out
    entry = QuietEntry(inbound.household_id, inbound.speaker_id, conversation_id, datetime.now(UTC), why, score,
                       inbound.cause)
    try:
        await services.get(OutsideRecord).quieted(entry)
    except OutsideRecordUnavailable:
        logs.warning(log, "initiative.quiet_unrecorded", conversation=conversation_id, why=why)
    return out
