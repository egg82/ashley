"""Every source asked at once for one hearer, each answering or named as unreachable (`find`)."""

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from collections.abc import Sequence

from .. import logs
from ..conversations.model import Hearer
from .model import Findings, Found, Kind, SourceDown

log = logging.getLogger("ashley.find")

TIMEOUT_S = 4.0
"""How long one source has before it is named unreachable; the others' records do not wait on it."""


class Source(ABC):
    """One system's search, behind that system's own access rule for `hearer`. `hearer.owner_only` means the answer
    reaches the speaker alone: a person's own session on a route, `ashley.channels.audience.owner_alone` on a turn."""

    kind: Kind

    @abstractmethod
    async def find(self, hearer: Hearer, query: str, limit: int) -> tuple[Found, ...] | None:
        """Up to `limit` records matching `query` that `hearer` may read, best first; None when this source does not
        serve `hearer` or the household has not connected it. Raises SourceDown when it cannot answer."""


async def find(sources: Sequence[Source], hearer: Hearer, query: str, limit: int,
               timeout_s: float = TIMEOUT_S) -> Findings:
    """`query` asked of every source at once, each given `timeout_s`. A source raising SourceDown or running out of time
    is unreachable, never an empty answer; any other exception is a defect and propagates. Logs `find.searched` with
    the person, each answering source's count, the unreachable ones and the duration, never the query or a record."""
    started = time.monotonic()
    got = await asyncio.gather(*(asyncio.wait_for(s.find(hearer, query, limit), timeout_s) for s in sources),
                               return_exceptions=True)
    found: list[Found] = []
    answered: list[Kind] = []
    unreachable: list[Kind] = []
    counts: dict[str, int] = {}
    for source, result in zip(sources, got, strict=True):
        if isinstance(result, (SourceDown, TimeoutError)):
            unreachable.append(source.kind)
        elif isinstance(result, BaseException):
            raise result
        elif result is not None:
            answered.append(source.kind)
            counts[source.kind] = len(result)
            found.extend(result[:limit])
    logs.info(log, "find.searched", person=hearer.speaker_id, household=hearer.household_id,
              counts=",".join(f"{k}:{n}" for k, n in counts.items()), unreachable=",".join(unreachable),
              duration_ms=int((time.monotonic() - started) * 1000))
    return Findings(tuple(found), tuple(answered), tuple(unreachable))
