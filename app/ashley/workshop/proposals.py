"""Which proposal to install each automation piece is waiting on the person's approval: read from the log, never stored."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from .commands import Effect, Installed, Proposed
from .model import Piece


@dataclass(frozen=True)
class Proposal:
    """Her proposal `seq` to install a piece, with what it proposed."""

    seq: int
    proposed: Proposed


def pending(pieces: Iterable[Piece], effects: Mapping[int, Effect]) -> dict[int, Proposal]:
    """By piece id, the newest accepted proposal of each piece that no Install of the piece came after, while it is of
    the piece's current version; `effects` holds at least every `Proposed` and `Installed` of the bench, by `seq`."""
    newest: dict[int, Proposal] = {}
    for seq in sorted(effects):
        effect = effects[seq]
        if isinstance(effect, Proposed):
            newest[effect.piece_id] = Proposal(seq, effect)
        elif isinstance(effect, Installed):
            newest.pop(effect.piece_id, None)
    versions = {p.id: p.version for p in pieces}
    return {piece: p for piece, p in newest.items() if versions.get(piece) == p.proposed.version}
