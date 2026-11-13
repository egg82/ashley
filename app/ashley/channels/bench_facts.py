"""The rows code shows beside her reply on a bench (`Receipts.facts`), each once: every choice row, and each guessed
number an unconfirmed check of the turn's run rests on. Recorded shown on the bench's log (`workshop.surface.surface`)
as the turn closes, so a later turn shows only what is new or changed."""

import logging

from .. import logs
from .. import services
from ..conversations.model import Fact
from ..runs.runs import Runs, RunsUnavailable
from ..workshop.measurements import Choice, shown_label, shown_value
from ..workshop.model import Owner
from ..workshop.model_report import open_guesses
from ..workshop.surface import surface
from ..workshop.workshop import WorkshopError
from .model import Inbound

log = logging.getLogger("ashley.channels")


async def shown(inbound: Inbound, turn_id: int) -> tuple[Fact, ...]:
    """The rows of the bench `inbound`'s turn `turn_id` is on, with a known speaker, that the person has not been
    shown, now recorded shown; none off a bench or when the workshop cannot be reached or the bench is closed (logged
    `bench.facts_unavailable` with the bench and the error's type). Its guessed numbers are those of `guesses`; when the
    runs cannot be read the turn shows its choices alone (logged `bench.guesses_unavailable`). Logs `bench.facts` with
    the bench and how many."""
    bench = inbound.bench_id if inbound.moved_to is None else inbound.moved_to
    if bench is None or inbound.speaker_id is None:
        return ()
    try:
        rows = await surface(Owner(inbound.household_id, inbound.speaker_id), bench,
                             await guesses(inbound.household_id, turn_id, bench))
    except WorkshopError as e:
        logs.warning(log, "bench.facts_unavailable", bench=bench, error=type(e).__name__)
        return ()
    if rows:
        logs.info(log, "bench.facts", bench=bench, shown=len(rows))
    return tuple(Fact(bench, piece_id, r.name, shown_label(r), shown_value(r), r.options if isinstance(r, Choice) else ())
                 for piece_id, r in rows)


async def guesses(household_id: int, turn_id: int, bench: int) -> frozenset[str]:
    """The names of the guessed numbers an unconfirmed check of the turn's latest run of each piece of `bench` rests on
    (`model_report.open_guesses`)."""
    try:
        runs = await services.get(Runs).bench_runs_of_turn(household_id, turn_id)
    except RunsUnavailable:
        logs.warning(log, "bench.guesses_unavailable", bench=bench)
        return frozenset()
    latest = {r.bench.piece_id: r for r in runs if r.bench is not None and r.bench.bench_id == bench}
    names: set[str] = set()
    for r in latest.values():
        if r.output is not None:
            names |= open_guesses(r.output, r.files)
    return frozenset(names)
