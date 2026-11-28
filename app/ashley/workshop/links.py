"""Links between a bench's pieces: the `Link` and `Unlink` Commands, their effects, and the pure rules `decide` judges
them by. A link is a fact about two pieces, not a change of either: it never touches a piece's text, version, place
or `changed_by`, so linking never makes an edit stale and an undo of a piece's change never waits on a link.

The bench keeps every link made and not unlinked, even while an end is off the layout (removed or shelved); a read
shows only those whose two ends are both on it (`visible`), so a piece brought back by an undo or a restore comes back
with its links. Which kinds exist is data (`workshop.json`'s `link_kinds`, `rules.Rules.link_kinds`)."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from .model import By, Piece
from .reasons import Reason


@dataclass(frozen=True)
class PieceLink:
    """Piece `from_id` is `kind` (`part_of`, `depends_on`, `version_of`, ...) of piece `to_id`."""

    from_id: int
    kind: str
    to_id: int


@dataclass(frozen=True)
class Link:
    """Link piece `from_id` to piece `to_id` as `kind`: both on the layout, not the same piece, not linked so already."""

    by: By
    from_id: int
    kind: str
    to_id: int

    @property
    def link(self) -> PieceLink:
        return PieceLink(self.from_id, self.kind, self.to_id)


@dataclass(frozen=True)
class Unlink:
    """Take away the link of `kind` from piece `from_id` to piece `to_id`, both on the layout."""

    by: By
    from_id: int
    kind: str
    to_id: int

    @property
    def link(self) -> PieceLink:
        return PieceLink(self.from_id, self.kind, self.to_id)


@dataclass(frozen=True)
class Linked:
    """`link` was made. It changes no piece, and is undone by an `Unlinked` of the same link."""

    link: PieceLink


@dataclass(frozen=True)
class Unlinked:
    """`link` was taken away. It changes no piece, and is undone by a `Linked` of the same link."""

    link: PieceLink


Links = frozenset[PieceLink]


def judged(pieces: tuple[Piece, ...], links: Links, command: Link | Unlink,
           kinds: Mapping[str, str]) -> Linked | Unlinked | Reason:
    """`command` judged against the layout's `pieces` and the bench's `links`, the first refusal that applies in this
    order: `no_such_piece` (an end not on the layout), `bad_link` (a piece linked to itself, or a kind not in `kinds`),
    then `already_linked` for a Link of a link the bench holds, `not_linked` for an Unlink of one it does not."""
    on = {p.id for p in pieces}
    if command.from_id not in on or command.to_id not in on:
        return "no_such_piece"
    if command.from_id == command.to_id or command.kind not in kinds:
        return "bad_link"
    held = command.link in links
    if isinstance(command, Link):
        return "already_linked" if held else Linked(command.link)
    return Unlinked(command.link) if held else "not_linked"


def linked(links: Links, effect: object) -> Links:
    """The bench's links after `effect`; any effect but a `Linked` or `Unlinked` leaves them as they are."""
    if isinstance(effect, Linked):
        return links | {effect.link}
    if isinstance(effect, Unlinked):
        return links - {effect.link}
    return links


def inverse(effect: Linked | Unlinked, links: Links) -> Linked | Unlinked | None:
    """The effect that undoes `effect` on the bench's `links` as they stand; None when the link is not as `effect` left
    it. An end off the layout does not stop it: the link is kept or dropped all the same, and shows again only with
    both ends back."""
    if isinstance(effect, Linked):
        return Unlinked(effect.link) if effect.link in links else None
    return Linked(effect.link) if effect.link not in links else None


def visible(links: Iterable[PieceLink], pieces: Iterable[Piece]) -> tuple[PieceLink, ...]:
    """The `links` whose two ends are both among `pieces` (the layout), by from, kind and to."""
    on = {p.id for p in pieces}
    return tuple(sorted((k for k in links if k.from_id in on and k.to_id in on),
                        key=lambda k: (k.from_id, k.kind, k.to_id)))
