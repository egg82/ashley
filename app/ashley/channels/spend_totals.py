"""Folding ledger tallies into the totals a report shows."""

from collections.abc import Iterable
from decimal import Decimal

from ..inference.spend_tally import Tally
from .spend_report import Spans, Totals

EMPTY = Totals(0, 0, 0, None, None, None, None, None, None, None)


def _count(values: Iterable[int | None]) -> int | None:
    present = [v for v in values if v is not None]
    return sum(present) if present else None


def _cost(values: Iterable[Decimal | None]) -> Decimal | None:
    present = [v for v in values if v is not None]
    return sum(present, Decimal(0)) if present else None


def combine(tallies: Iterable[Tally]) -> Totals:
    """The tallies as one, None-aware: a sum over rows none of which had a value stays None."""
    rows = list(tallies)
    if not rows:
        return EMPTY
    return Totals(sum(t.calls for t in rows), sum(t.metered for t in rows), sum(t.priced for t in rows),
                  _count(t.input_tokens for t in rows), _count(t.output_tokens for t in rows),
                  _count(t.cache_read_tokens for t in rows), _count(t.cache_write_tokens for t in rows),
                  _count(t.audio_ms for t in rows), _count(t.characters for t in rows), _cost(t.cost_usd for t in rows))


def spans_of(tallies: Iterable[Tally]) -> Spans:
    rows = list(tallies)
    return Spans(*(combine(t for t in rows if t.window == name) for name in ("today", "week", "month")))
