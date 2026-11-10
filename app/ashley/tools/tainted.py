"""What tainted the turn a tool call runs in, for the tools whose writes outlast it: `Outside` binds it around each call
it runs (`bound`), and a reminder, a watch, a bench piece or a list a tainted turn writes records it (`current`), so
what is read back later carries it (`decisions.md`, "A turn that has read outside words asks before it does anything
consequential the person did not ask for"). None outside a tainted turn, which is also what a call outside any turn sees."""

from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar

from ..workshop.model import By

_BOUND: ContextVar[str | None] = ContextVar("ashley_tainted", default=None)
_MADE_IN: ContextVar[tuple[int, int] | None] = ContextVar("ashley_made_in", default=None)


def current() -> str | None:
    """The origin or the tool that tainted the turn this call runs in; None when it is not tainted."""
    return _BOUND.get()


def made_in() -> tuple[int, int] | None:
    """The conversation and turn this call runs in when that turn is tainted, which a reminder or watch it makes keeps
    (`Reminder.made_in`); None when the turn is not tainted or has no stored turn."""
    return _MADE_IN.get()


@contextmanager
def bound(by: str | None, turn: tuple[int, int] | None = None) -> Generator[None]:
    """`current` is `by` inside the block, and `made_in` is `turn` when `by` is set."""
    token, turn_token = _BOUND.set(by), _MADE_IN.set(turn if by is not None else None)
    try:
        yield
    finally:
        _MADE_IN.reset(turn_token)
        _BOUND.reset(token)


def her() -> By:
    """Her as the author of a change to a bench: `outside` when the turn it is made in has read outside words, which marks
    the piece it adds or edits (`workshop.model.Piece.outside`)."""
    return By(None, outside=current() is not None)
