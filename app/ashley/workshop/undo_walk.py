"""Which command an Undo should name next: a walk over a bench's recent log, newest first, never a stored pointer."""

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class Step:
    """One command of the log, reduced to what the walk needs: whether it was accepted, for an Undo the `seq` it
    undid (None for any other command), and whether it is a Run, a Propose or a Cue (`run`), which changed no piece and is
    never undone."""

    seq: int
    accepted: bool
    undid: int | None = None
    run: bool = False


def next_undo(log: Iterable[Step]) -> int | None:
    """The `seq` of the newest accepted command of `log` (the bench's last `undo_window` commands, oldest first) that is not an Undo and has no accepted Undo
    after it, so each press of Undo takes back the next-older change and none is taken twice; None when there is
    none. A Run, a Propose or a Cue is passed over, as a refusal is. It names a command even when its piece has changed since: the Undo is then refused `changed_since` and the
    walk stops there, never reaching past it."""
    undone: set[int] = set()
    for step in reversed(list(log)):
        if not step.accepted or step.run:
            continue
        if step.undid is not None:
            undone.add(step.undid)
        elif step.seq not in undone:
            return step.seq
    return None
