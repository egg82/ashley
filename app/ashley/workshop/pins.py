"""Judging a Move (`decide`): its order, and the pin and box it sets, clears or keeps. Only a person's moves set a pin
or a box, since her tools offer neither (`tools.bench_specs`); `decide` does not judge whose layout it is."""

from .commands import Keep, Move, Moved, Reason
from .model import Box, Piece, Pin, Place
from .rules import Layout


def moved(piece: Piece, count: int, command: Move, layout: Layout | None) -> Moved | Reason:
    """`piece`, one of the `count` pieces on the layout, moved by `command` under `layout` (None: a screen's rules,
    which set no pin or box). `bad_place` for an order past the last piece's, or a pin or box `command` sets that
    `layout` does not hold. A pin or box `command` leaves `KEEP` stays as the piece has it."""
    if command.place.order >= count:
        return "bad_place"
    pin = piece.place.pin if isinstance(command.pin, Keep) else command.pin
    box = piece.place.box if isinstance(command.box, Keep) else command.box
    if not _holds(layout, None if isinstance(command.pin, Keep) else command.pin,
                  None if isinstance(command.box, Keep) else command.box):
        return "bad_place"
    return Moved(piece.id, piece.place, Place(command.place.order, command.place.size, pin, box))


def _holds(layout: Layout | None, pin: Pin | None, box: Box | None) -> bool:
    """Whether `layout` holds the `pin` and `box` a move sets (None for one it clears or keeps)."""
    if pin is None and box is None:
        return True
    if layout is None:
        return False
    pin_ok = pin is None or max(abs(pin.x), abs(pin.y)) <= layout.pin_reach
    box_ok = box is None or (layout.min_w <= box.w <= layout.max_w and layout.min_h <= box.h <= layout.max_h)
    return pin_ok and box_ok
