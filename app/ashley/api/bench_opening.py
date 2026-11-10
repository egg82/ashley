"""Opening a bench with an ask: the ask is the person's first message in the bench's talk, and she answers it in a bench
turn that leads, as on a bench she opened herself (`Inbound.lead`). The turn runs on its own after the bench is
returned; the bench's id is the message's `source`, so one bench is one turn."""

import logging

from .. import logs
from ..channels.model import Inbound
from ..channels.respond import RespondError, background, respond
from ..people.model import Person
from ..workshop.model import thread_of

log = logging.getLogger("ashley.api")


def inbound_for(who: Person, bench_id: int, ask: str) -> Inbound:
    """`ask` as the turn loop takes it: the owner's message on the bench's thread, leading, handed in once."""
    return Inbound(household_id=who.household_id, thread=thread_of(bench_id), text=ask, kind="brainstorm",
                   medium="text", audience="owner", speaker_id=who.id, shared=False, place=None, channel="web",
                   later=True, later_by="turn", bench_id=bench_id, on_page=True, source=f"bench-opened:{bench_id}",
                   lead=True, taint=None)


def start(who: Person, bench_id: int, ask: str) -> None:
    """Begin her turn on `ask` without waiting for it; a turn that fails is logged `bench.ask_failed`."""
    background(_answer(inbound_for(who, bench_id, ask)))


async def _answer(inbound: Inbound) -> None:
    try:
        await respond(inbound)
    except RespondError as e:
        logs.warning(log, "bench.ask_failed", bench=inbound.bench_id, error=type(e).__name__)
