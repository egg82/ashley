"""What an Effect does to a bench's pieces, and the Effect that undoes one. Pure helpers of `decide`."""

from collections.abc import Mapping
from dataclasses import replace

from .commands import (Added, Archived, Cued, Edited, Effect, Installed, Moved, Pointed, Proposed, Ran, Removed, Renamed,
                       Restored, Uninstalled, piece_of)
from .model import Piece, Place


def apply(pieces: tuple[Piece, ...], effect: Effect, seq: int) -> tuple[Piece, ...]:
    """`pieces` (in order) after `effect`, made by command `seq`, renumbered so their orders are 0 to n-1 again. A
    `Ran`, `Cued`, `Pointed`, `Proposed`, `Installed`, `Uninstalled` or `Renamed` leaves them as they are (what an install changes is
    outside the bench); an archive takes the piece out as a removal does, a restore puts it in as an add."""
    if isinstance(effect, (Ran, Cued, Pointed, Proposed, Installed, Uninstalled, Renamed)):
        return pieces
    if isinstance(effect, (Added, Restored)):
        listed = list(pieces)
        listed.insert(effect.piece.place.order, effect.piece)
        return _renumbered(listed)
    if isinstance(effect, (Removed, Archived)):
        return _renumbered([p for p in pieces if p.id != effect.piece.id])
    if isinstance(effect, Edited):
        return tuple(replace(p, text=effect.after, version=p.version + 1, changed_by=seq, outside=p.outside or effect.outside)
                     if p.id == effect.piece_id else p for p in pieces)
    listed = [p for p in pieces if p.id != effect.piece_id]
    moving = next(p for p in pieces if p.id == effect.piece_id)
    listed.insert(effect.after.order, replace(moving, place=effect.after, changed_by=seq))
    return _renumbered(listed)


def titled(title: str, effect: Effect) -> str:
    """The bench's title after `effect`."""
    return effect.after if isinstance(effect, Renamed) else title


def shelved(shelf: tuple[Piece, ...], effect: Effect, seq: int) -> tuple[Piece, ...]:
    """The shelf (most recently archived first) after `effect`, made by command `seq`: an archived piece goes first,
    its `changed_by` the archive's; a restored one leaves it; any other effect leaves it as it is."""
    if isinstance(effect, Archived):
        return (replace(effect.piece, changed_by=seq), *shelf)
    if isinstance(effect, Restored):
        return tuple(p for p in shelf if p.id != effect.piece.id)
    return shelf


def settled(effect: Effect, effects: Mapping[int, Effect], undos: Mapping[int, int], done_seq: int) -> bool:
    """Whether the piece `effect` (command `done_seq`) changed is as that command left it: every later effect on the
    piece is a command that a later undo took back, or such an undo. A `Ran`, a `Cued`, a `Pointed` or a `Proposed` changed nothing, so it
    never counts; an `Installed` does, so a change before an install is undone only after the install is."""
    taken_back = set(undos.values())
    return all(s in taken_back or undos.get(s, 0) > done_seq
               for s, e in effects.items()
               if s > done_seq and not isinstance(e, (Ran, Cued, Pointed, Proposed)) and piece_of(e) == piece_of(effect))


def inverse(effect: Effect, pieces: tuple[Piece, ...], shelf: tuple[Piece, ...], title: str,
            effects: Mapping[int, Effect], undos: Mapping[int, int], done_seq: int, seq: int) -> Effect | None:
    """The effect that undoes `effect` (what command `done_seq` did) as command `seq`, on `pieces`, `shelf` and bench
    `title` as they stand, `effects` as done so far and `undos` (undo `seq` to the `seq` it undid); None when the piece has changed
    since (`settled` fails, or a removed piece is back, or `effect` is a `Ran`, `Cued`, `Pointed` or `Proposed`, which nothing undoes). An
    archive is undone by restoring the piece to its old order (or last), a restore by archiving it again, an install
    by an `Uninstalled` naming it, a rename by renaming the bench back."""
    if isinstance(effect, (Ran, Cued, Pointed, Proposed, Uninstalled)):
        return None
    if isinstance(effect, Renamed):
        return Renamed(title, effect.before) if settled(effect, effects, undos, done_seq) else None
    current = next((p for p in pieces if p.id == piece_of(effect)), None)
    if not settled(effect, effects, undos, done_seq):
        return None
    if isinstance(effect, Archived):
        kept = next((p for p in shelf if p.id == effect.piece.id), None)
        if kept is None:
            return None
        order = min(effect.piece.place.order, len(pieces))
        return Restored(replace(kept, place=replace(kept.place, order=order), changed_by=seq))
    if isinstance(effect, Removed):
        if current is not None:
            return None
        order = min(effect.piece.place.order, len(pieces))
        return Added(replace(effect.piece, place=replace(effect.piece.place, order=order), changed_by=seq))
    if current is None:
        return None
    if isinstance(effect, Added):
        return Removed(current)
    if isinstance(effect, Restored):
        return Archived(current)
    if isinstance(effect, Installed):
        return Uninstalled(current.id, done_seq, effect.automation_id)
    if isinstance(effect, Edited):
        return Edited(current.id, current.text, effect.before)
    last = len(pieces) - 1
    return Moved(current.id, current.place, Place(min(effect.before.order, last), effect.before.size))


def _renumbered(listed: list[Piece]) -> tuple[Piece, ...]:
    return tuple(p if p.place.order == i else replace(p, place=replace(p.place, order=i)) for i, p in enumerate(listed))
