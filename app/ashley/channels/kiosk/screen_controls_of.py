"""The touch controls a device's screen shows: the body of its `controls` piece, read from the Workshop."""

from ...workshop.screen_controls import Control, decode
from ...workshop.workshop import ScreenView


def controls_piece(view: ScreenView) -> tuple[int, int, tuple[Control, ...]] | None:
    """The screen's controls piece as its id, version and buttons; None when it has none."""
    piece = next((p for p in view.pieces if p.kind == "controls"), None)
    return None if piece is None else (piece.id, piece.version, decode(piece.text.body))
