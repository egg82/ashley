"""The wire shape of a device's screen layout, as the kiosk page reads it."""

from pydantic import BaseModel

from ..workshop.model import Size


class KioskPiece(BaseModel):
    """One piece of the screen: `id` its stable key, `kind` what it is (`clock`, `home`, `conversation`, `controls`),
    `order` its place among the pieces (0 first, no gaps) and `size` how much of the row it takes (`small` a quarter,
    `medium` a half, `large` three quarters, `full` the row)."""

    id: int
    kind: str
    order: int
    size: Size


class KioskLayout(BaseModel):
    """The device's screen as it is laid out. `laid_out` is false while nothing has changed it, and the page then shows its
    fixed layout; `seq` is the last change's number, 0 when not laid out; `placed` are the pieces in order."""

    laid_out: bool
    seq: int
    placed: list[KioskPiece]
