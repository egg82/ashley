"""What she remembers for one message, and which of it her reply says it relied on (`respond` steps 3 and 6)."""

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime

from .. import services
from ..inference.reply import Reply
from ..memory.memory import Memory, MemoryUnavailable
from ..memory.model import Asker, Recalled
from .model import Inbound
from .speaker import Who


@dataclass(frozen=True)
class Remembered:
    """What memory offers one reply: `standing` (`Memory.profile`) and `recalled` (`Memory.recall`), both None when
    memory cannot be reached."""

    standing: tuple[Recalled, ...] | None
    recalled: tuple[Recalled, ...] | None


async def remembered(inbound: Inbound, who: Who) -> Remembered:
    """`Memory.profile` and `Memory.recall` on the message's text for the speaker, fetched together, owner-only when
    the channel's audience is `owner`. Either being unreachable makes both None, and the reply goes on without."""
    asker = Asker(inbound.household_id, who.speaker.id if who.speaker is not None else None,
                  inbound.audience == "owner", datetime.now(UTC))
    memory = services.get(Memory)
    try:
        standing, recalled = await asyncio.gather(memory.profile(asker), memory.recall(asker, inbound.text))
    except MemoryUnavailable:
        return Remembered(None, None)
    return Remembered(standing, recalled)


def offered_ids(standing: tuple[Recalled, ...] | None, recalled: tuple[Recalled, ...] | None) -> frozenset[int]:
    """The fact ids a reply was shown, from either tier."""
    return frozenset(r.fact.id for tier in (standing, recalled) for r in tier or ())


def used(reply: Reply, recalled: tuple[Recalled, ...] | None,
         standing: tuple[Recalled, ...] | None) -> tuple[tuple[int, ...], int]:
    """The reply's `used_facts` that were offered to it from either tier, in its order without repeats, and how many
    ids it named that were not."""
    offered = offered_ids(standing, recalled)
    named = tuple(dict.fromkeys(reply.used_facts))
    kept = tuple(i for i in named if i in offered)
    return kept, len(named) - len(kept)


def ids(tier: tuple[Recalled, ...] | None) -> str:
    """The fact ids of one tier as `respond.done` logs them: comma-separated in the order offered, empty for none,
    `unavailable` for a tier memory could not give."""
    return "unavailable" if tier is None else ",".join(str(r.fact.id) for r in tier)
