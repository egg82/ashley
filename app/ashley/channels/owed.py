"""Errands in a reply (`decisions.md`, "What she could not do for want of a source, she does once it answers, and says
so next time"): what she owes from `Reply.owed`, and what she tells of errands done since. All of it goes through the
`Errands` service; a store out of reach is logged and the reply goes on."""

import logging
from collections.abc import Collection
from zoneinfo import ZoneInfo

from .. import logs, services
from ..errands.config import CONFIG
from ..errands.errands import Errands, ErrandsUnavailable
from ..errands.model import Done
from ..inference.reply import Reply
from ..people.model import Household, Person
from ..stamp import stamp
from .model import Inbound

log = logging.getLogger("ashley.channels")


def kept(reply: Reply, unreachable: tuple[str, ...] | None, speaker: Person | None, changed: bool) -> str | None:
    """`reply.owed` when the speaker is known, it is a source this turn's catalogue found out of reach
    (`Catalogue.unreachable`; `unreachable` None when there was no catalogue), and the turn has not `changed`
    anything (`Steps.changed`: the errand re-runs the whole ask, which would do that part twice), else None."""
    if speaker is None or unreachable is None or changed or reply.owed not in unreachable:
        return None
    return reply.owed


async def settle(reply: Reply, unreachable: tuple[str, ...] | None, speaker: Person | None, conversation_id: int,
                 turn_id: int, away: tuple[Done, ...], hers: int | None, changed: bool) -> None:
    """After her answer to the person turn `turn_id` is stored (`hers`, its id, None when the conversation refused it):
    the errand it owes (`kept`) stored, and `away`, the results it was shown, marked told."""
    source = kept(reply, unreachable, speaker, changed)
    if source is not None and speaker is not None:
        await owe(source, speaker, conversation_id, turn_id)
    if hers is not None:
        await told(away, conversation_id)


def fields(reply: Reply, unreachable: tuple[str, ...] | None, speaker: Person | None,
           away: tuple[Done, ...], changed: bool) -> dict[str, str | int]:
    """What `respond.done` logs of errands: `owed`, the source `kept` or `none`; `owed_dropped`, 1 when the reply set
    `owed` and it was not kept (including for a `changed` turn); `told`, the ids of `away` comma-separated in the order shown. Never an ask or a result."""
    source = kept(reply, unreachable, speaker, changed)
    return {"owed": source or "none", "owed_dropped": int(reply.owed is not None and source is None),
            "told": ",".join(str(d.id) for d in away)}


async def owe(source: str, speaker: Person, conversation_id: int, turn_id: int) -> None:
    """The errand for the person turn `turn_id`, stored once. A store that cannot be reached or refuses the turn is
    logged `respond.owed_unrecorded` (the turn id, never the source's request) and the reply goes on."""
    try:
        await services.get(Errands).owe(speaker.household_id, speaker.id, conversation_id, turn_id, source)
    except (ErrandsUnavailable, ValueError) as e:
        logs.warning(log, "respond.owed_unrecorded", conversation=conversation_id, said=turn_id, error=type(e).__name__)


async def untold(inbound: Inbound, speaker: Person | None) -> tuple[Done, ...]:
    """The speaker's finished errands this reply may carry (`Errands.untold`, at most `tell_max`); nothing for an
    unknown speaker, an unprompted turn, or a store out of reach (logged `respond.errands_unavailable`)."""
    if speaker is None or inbound.unprompted:
        return ()
    try:
        return await services.get(Errands).untold(speaker.id, CONFIG.tell_max, inbound.audience == "owner")
    except ErrandsUnavailable:
        logs.warning(log, "respond.errands_unavailable")
        return ()


def lines(done: tuple[Done, ...], household: Household) -> tuple[str, ...]:
    """One line per errand done, `(<when it finished>) <what she did>`, in the order given."""
    zone = ZoneInfo(household.timezone)
    return tuple(f"({stamp(d.finished_at, zone)}) {d.result}" for d in done)


async def told(done: Collection[Done], conversation_id: int) -> None:
    """`done` marked told. A store that cannot record it is logged `respond.told_unrecorded` and costs only saying it
    again."""
    if not done:
        return
    try:
        await services.get(Errands).told([d.id for d in done])
    except ErrandsUnavailable:
        logs.warning(log, "respond.told_unrecorded", conversation=conversation_id)
