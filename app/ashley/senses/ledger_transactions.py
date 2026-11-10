"""The deposit sense's view of the household's ledger: its transactions as the records criteria are judged over
(`ashley.criteria.record.Transaction`), read through the Ledger service (`ashley.ledger.ledger`). Another budgeting app
means another Ledger adapter; no rule or predicate changes. Raises LedgerFailed, LedgerUnavailable, NotConnected."""

from datetime import date

from .. import services
from ..criteria.record import Direction, Transaction
from ..ledger.ledger import Ledger
from ..ledger.model import Entry, Kind, Page, TransactionQuery
from .deposit_config import CONFIG

_MAX_ID = 80
_KIND: dict[Direction, Kind] = {"in": "income", "out": "expense"}
"""The ledger's word for each direction, which is also the classification a transaction going that way has."""


async def read(household_id: int, start: date, directions: tuple[Direction, ...]) -> tuple[list[Transaction], date | None]:
    """The household's transactions going each of `directions` dated `start` on, and the day they are all read through:
    None when every one was read, else the earliest of the days each direction was cut at. Raises LedgerFailed,
    LedgerUnavailable, NotConnected."""
    found: list[Transaction] = []
    cuts: list[date] = []
    for direction in directions:
        got, through = await _read_direction(household_id, start, direction)
        found += got
        if through is not None:
            cuts.append(through)
    return found, min(cuts, default=None)


async def _read_direction(household_id: int, start: date, direction: Direction) -> tuple[list[Transaction], date | None]:
    """One direction's transactions dated `start` on, and the day they are all read through: None when every one was
    read. The ledger lists newest first, so when `max_pages` cannot hold them all the oldest pages are read, and the
    day is the newest one read, so the next poll continues from it."""
    first = await _page(household_id, start, 1, direction)
    total = first.total
    pages = 1 if total is None else -(-total // CONFIG.per_page)
    wanted = range(1, pages + 1) if pages <= CONFIG.max_pages else range(pages, pages - CONFIG.max_pages, -1)
    rows = [t for n in wanted for t in (first if n == 1 else await _page(household_id, start, n, direction)).rows]
    found = [d for d in (deposit_from(t, direction) for t in rows) if d is not None]
    if total is None or pages <= CONFIG.max_pages:
        return found, None
    return found, max((d.day for d in found), default=start)


async def _page(household_id: int, start: date, number: int, direction: Direction) -> Page[Entry]:
    return await services.get(Ledger).transactions(household_id, TransactionQuery(
        per_page=CONFIG.per_page, start=start.isoformat(), kind=_KIND[direction], page=number))


def deposit_from(t: Entry, direction: Direction) -> Transaction | None:
    """None for a transaction a rule cannot judge: no id to derive a reminder from, no amount, or a date that is not one."""
    if t.id is None or len(t.id) > _MAX_ID or t.cents is None:
        return None
    try:
        day = date.fromisoformat(t.date)
    except ValueError:
        return None
    names = tuple(n for n in (t.merchant, t.name) if n)
    counts = t.classification == _KIND[direction] and not t.transfer and not t.excluded and not t.split
    return Transaction(t.id, day, t.account_id or "", t.cents, counts, names, direction)
