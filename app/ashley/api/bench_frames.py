"""Measuring whether the sites on a bench can be framed. When a bench is read and a site piece's address has no measure
yet, the site is asked once in the background (`FrameProbe`: the page reader's request, judged from its headers by
`tools.frame_policy`) and the answer recorded on the bench, and the person's open screens are told the
bench changed so they read it again. An address that could not be asked is recorded as unknown, so it is not asked on
every read. The `bench.frame` line carries the bench, piece and outcome, never the address."""

import logging
import time

from .. import logs, services
from ..channels.respond import background
from ..live.events import BenchChanged, Shown
from ..live.live import Live
from ..workshop.frame_probe import FrameProbe
from ..workshop.model import Owner, Piece
from ..workshop.rules import Rules
from ..workshop.workshop import BenchView, Workshop, WorkshopUnavailable

log = logging.getLogger("ashley.api")
_asking: set[tuple[int, str]] = set()


def addresses_unmeasured(view: BenchView, rules: Rules) -> dict[str, Piece]:
    """The pieces of site kinds on the bench's layout whose address has no measure, by address."""
    return {p.text.body.strip(): p for p in view.pieces
            if (kind := rules.kinds.get(p.kind)) is not None and kind.format == "site"
            and p.text.body.strip() and p.text.body.strip() not in view.frames}


def measure_in_background(owner: Owner, view: BenchView, rules: Rules, origin: str) -> None:
    """Ask each unmeasured address of the bench, at most once at a time per bench and address."""
    for url, piece in addresses_unmeasured(view, rules).items():
        key = (view.bench.id, url)
        if key not in _asking:
            _asking.add(key)
            background(_measure(owner, view.bench.id, piece.id, url, origin, key))


async def _measure(owner: Owner, bench_id: int, piece_id: int, url: str, origin: str, key: tuple[int, str]) -> None:
    started = time.monotonic()
    try:
        frame = await services.get(FrameProbe).measure(url, origin)
        outcome = "unknown" if frame.frameable is None else "frameable" if frame.frameable else "refused"
        await services.get(Workshop).record_site_frame(owner.household_id, bench_id, url, frame)
        services.get(Live).publish(BenchChanged(Shown(owner.household_id, owner.person_id), bench_id, 0))
    except WorkshopUnavailable:
        outcome = "unrecorded"
    finally:
        _asking.discard(key)
    logs.info(log, "bench.frame", bench=bench_id, piece=piece_id, outcome=outcome,
              duration_ms=int((time.monotonic() - started) * 1000))

