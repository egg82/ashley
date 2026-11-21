"""The household's filament stock as she sees it, whichever app keeps it: plain records whose fields are stated in
stock terms. An adapter (for Bambuddy, `ashley.bambuddy.stock`) fills them from its backend's own shapes; nothing outside
it knows those shapes."""

from dataclasses import dataclass
from typing import Literal

Reason = Literal["refused", "unreachable", "unrecognised"]
"""Why a read failed: `refused`, the backend turned the household's key away; `unreachable`, no answer in time or a
server error; `unrecognised`, what answered is not that backend's API."""


@dataclass(frozen=True)
class Spool:
    """A spool in stock. `id` is the backend's, and the one `ashley.printing.model.Slot.spool_id` names when the spool is
    loaded in a printer. `material` is the filament type ("PLA"), `brand` and `colour_name` as the household or the
    filament catalogue it was added from wrote them, `colour` the hex colour ("#RRGGBB"), `remaining_grams` what is left
    of the filament and `full_grams` what a new spool holds, `location` where it is kept. A field the backend leaves out
    is None."""

    id: str
    material: str | None
    brand: str | None
    colour_name: str | None
    colour: str | None
    remaining_grams: int | None
    full_grams: int | None
    location: str | None


@dataclass(frozen=True)
class Page[T]:
    """What one read holds, and `total`, how many the backend holds in all."""

    rows: tuple[T, ...]
    total: int


class StockFailed(Exception):
    def __init__(self, reason: Reason) -> None:
        super().__init__(reason)
        self.reason: Reason = reason


class StockUnavailable(Exception):
    """The household's link to its stock cannot be read."""


class NotConnected(Exception):
    """The household has no filament stock."""
