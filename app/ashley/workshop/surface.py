"""Recording, at the end of her turn on a bench, the rows the person is about to be shown beside her reply."""

from itertools import groupby

from .. import services
from . import rules as workshop_rules
from .commands import ShownRow, Surfaced
from .measurements import Row, shown_value
from .model import HER, Owner
from .surfacing import unshown
from .workshop import Workshop

_RULES = workshop_rules.load()


async def surface(owner: Owner, bench_id: int, guessed: frozenset[str] = frozenset()) -> tuple[tuple[int, Row], ...]:
    """Every choice row of `owner`'s bench `bench_id`, and each guessed number named in `guessed`, not yet shown
    (`surfacing.unshown`), recorded as shown by one `Surfaced` of hers per piece; the (piece id, row) pairs whose
    Surfaced was accepted. A piece that changed between the read and the command is refused `bad_rows` and its rows wait
    for the next turn. Raises BenchNotFound, BenchClosed, WorkshopUnavailable."""
    shop = services.get(Workshop)
    view = await shop.read(owner, bench_id)
    shown: list[tuple[int, Row]] = []
    for piece_id, group in groupby(unshown(view.pieces, view.surfaced, _RULES, guessed), key=lambda found: found[0]):
        rows = [row for _, row in group]
        applied = await shop.apply(owner, bench_id, Surfaced(HER, piece_id, tuple(ShownRow(r.name, shown_value(r)) for r in rows)))
        if applied.outcome == "accepted":
            shown.extend((piece_id, r) for r in rows)
    return tuple(shown)
