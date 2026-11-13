"""What a turn reads before its first model step: the tools on offer, what she remembers, whether the reply may go to
a phone, the carried turns, what she did while away and the system prompt built from them (`respond` step 3)."""

import asyncio
from collections.abc import Awaitable, Mapping
from dataclasses import dataclass

from ..conversations.model import Carried
from ..errands.model import Done
from ..inference.model import SystemPrompt
from ..persona import persona
from ..tools.tools import Catalogue, Tools
from . import aloud, owed, prompt, recall, taste, to_phone, tool_loop
from .model import Inbound
from .speaker import Who


@dataclass(frozen=True)
class Prompted:
    """`catalogue` is None when the tools could not be reached; `phone` is the person id of `to_phone.reachable`; `system`
    is `persona.system` of the turn's kind over `context`."""

    catalogue: Catalogue | None
    remembered: recall.Remembered
    phone: int | None
    carried: Carried
    away: tuple[Done, ...]
    context: persona.Context
    system: Mapping[str, SystemPrompt]


async def build(inbound: Inbound, who: Who, source: Tools, carried: Awaitable[Carried]) -> Prompted:
    """The turn's tools (`tool_loop.offered` of `source`), memory, phone reach, `carried` and owed errand results read
    together, then the system prompt for each variant (`prompt.system`) with the household's persona overrides."""
    taste_read = asyncio.create_task(taste.overrides(inbound.household_id))
    catalogue, remembered, phone, page_open, got, away = await asyncio.gather(
        tool_loop.offered(source), recall.remembered(inbound, who), to_phone.reachable(inbound, who.speaker),
        to_phone.looking(inbound, who.speaker), carried, owed.untold(inbound, who.speaker))
    context = prompt.context(who, inbound.place, catalogue, remembered.recalled, remembered.standing or (),
                             phone=phone is not None, page_open=page_open if phone is not None else None,
                             aloud=aloud.offered(inbound), overhears=inbound.overhears,
                             said_before=prompt.said_before(got.relevant, who.household),
                             while_away=owed.lines(away, who.household), overrides=await taste_read)
    return Prompted(catalogue, remembered, phone, got, away, context, persona.system(inbound.kind, context))
