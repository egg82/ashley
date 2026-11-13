"""The choice rows code shows beside her reply on a bench (`Receipts.facts`), each once: recorded shown on the bench's
log (`workshop.surface.surface`) as the turn closes, so a later turn shows only what is new or changed."""

import logging

from .. import logs
from ..conversations.model import Fact
from ..workshop.model import Owner
from ..workshop.surface import surface
from ..workshop.workshop import WorkshopError
from .model import Inbound

log = logging.getLogger("ashley.channels")


async def shown(inbound: Inbound) -> tuple[Fact, ...]:
    """The rows of the bench `inbound`'s turn is on, with a known speaker, that the person has not been shown, now
    recorded shown; none off a bench or when the workshop cannot be reached or the bench is closed (logged
    `bench.facts_unavailable` with the bench and the error's type). Logs `bench.facts` with the bench and how many."""
    bench = inbound.bench_id if inbound.moved_to is None else inbound.moved_to
    if bench is None or inbound.speaker_id is None:
        return ()
    try:
        rows = await surface(Owner(inbound.household_id, inbound.speaker_id), bench)
    except WorkshopError as e:
        logs.warning(log, "bench.facts_unavailable", bench=bench, error=type(e).__name__)
        return ()
    if rows:
        logs.info(log, "bench.facts", bench=bench, shown=len(rows))
    return tuple(Fact(bench, piece_id, r.name, r.label, r.value, r.options) for piece_id, r in rows)
