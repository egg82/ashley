"""Bambuddy as the household's filament Stock (`ashley.stock.stock`): its spools, read through its spoolman inventory
routes (`GET /api/v1/spoolman/inventory/spools`, which relays the household's Spoolman) and turned from `wire`'s shape
into the stock's neutral records. Every answered call moves the connection's `checked_at`. Nothing outside this module,
`wire` and `colour` knows Bambuddy's field names."""

from ..stock.model import NotConnected, Page, Reason, Spool, StockFailed, StockUnavailable
from ..stock.stock import Stock
from . import wire
from .client import Reason as BambuddyReason
from .colour import hex_of
from .read import Reader

_REASON: dict[BambuddyReason, Reason] = {"refused": "refused", "unreachable": "unreachable",
                                         "not_bambuddy": "unrecognised", "not_found": "unrecognised"}

_READER = Reader("stock", StockUnavailable, NotConnected, lambda r: StockFailed(_REASON[r]))


class BambuddyStock(Stock):
    async def connected(self, household_id: int) -> bool:
        return await _READER.opened(household_id) is not None

    async def spools(self, household_id: int, limit: int) -> Page[Spool]:
        opened = await _READER.need(household_id)
        got = await _READER.get(opened, "/api/v1/spoolman/inventory/spools", {}, wire.Spools)
        if got is None:
            raise StockFailed("unrecognised")
        held = sorted((s for s in got.root if s.archived_at is None), key=_left, reverse=True)
        return Page(tuple(spool_from(s) for s in held[:limit]), len(held))


def _left(s: wire.Spool) -> float:
    grams = remaining(s)
    return -1.0 if grams is None else grams


def remaining(s: wire.Spool) -> int | None:
    """What a spool has left, in grams, from the weight a new one holds less what was used; never below nothing."""
    if s.label_weight is None:
        return None
    return max(0, round(s.label_weight - (s.weight_used or 0)))


def spool_from(s: wire.Spool) -> Spool:
    return Spool(id=str(s.id), material=s.material, brand=s.brand, colour_name=s.color_name, colour=hex_of(s.rgba),
                 remaining_grams=remaining(s), full_grams=s.label_weight, location=s.storage_location or None)
