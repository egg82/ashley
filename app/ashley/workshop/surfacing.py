"""Which rows of a bench the person has not been shown, and the judgement of a `Surfaced` that records them shown
(`decisions.md`, "Each choice she sets is shown to the person once"): every choice row, and a guessed number an
unconfirmed check of the turn's run rests on. Pure: the bench's pieces, the rows already shown (`BenchView.surfaced`,
read from the log) and the guessed names in, rows out."""

from collections.abc import Iterable

from . import measurements
from .commands import Effect, Shown, ShownRow, Surfaced
from .model import Piece
from .reasons import Reason
from .rules import Rules

Seen = frozenset[tuple[int, ShownRow]]
"""Every (piece id, row) some accepted `Surfaced` named."""


def unshown(pieces: Iterable[Piece], seen: Seen, rules: Rules,
            guessed: frozenset[str] = frozenset()) -> tuple[tuple[int, measurements.Row], ...]:
    """Each row of the measurements pieces among `pieces` whose name and shown value (`measurements.shown_value`) no
    `Surfaced` of its piece named, by piece in the order given and row in the piece's order: a choice row whatever its
    source, and a guessed number named in `guessed`, in the first piece that holds that name (a model run reads the
    first). A piece of an outside kind, or one a turn that had read outside words wrote, is skipped: its rows are not
    household words."""
    found: list[tuple[int, measurements.Row]] = []
    named: set[str] = set()
    for p in pieces:
        kind = rules.kinds.get(p.kind)
        if kind is None or kind.format != "measurements":
            continue
        household = _household_measurements(p, rules)
        for row in measurements.items_of(p.text.body) or ():
            first = row.name not in named
            named.add(row.name)
            wanted = isinstance(row, measurements.Choice) or (first and row.name in guessed and not measurements.confirmed(row))
            if household and wanted and (p.id, ShownRow(row.name, measurements.shown_value(row))) not in seen:
                found.append((p.id, row))
    return tuple(found)


def judged(piece: Piece, command: Surfaced, rules: Rules) -> Effect | Reason:
    """`decide`'s judgement of `command` on `piece`: `unknown_kind`, then `bad_rows` unless `piece` is a measurements
    piece of household words (`unshown`'s test) and the rows are one or more distinct names, each a row the piece
    holds now with that shown value. Its effect, `Shown`, changes no piece."""
    if piece.kind not in rules.kinds:
        return "unknown_kind"
    held = {(r.name, measurements.shown_value(r)) for r in measurements.items_of(piece.text.body) or ()
            } if _household_measurements(piece, rules) else set[tuple[str, str]]()
    names = [r.name for r in command.rows]
    if not names or len(set(names)) != len(names) or any((r.name, r.value) not in held for r in command.rows):
        return "bad_rows"
    return Shown(piece.id, command.rows)


def _household_measurements(piece: Piece, rules: Rules) -> bool:
    kind = rules.kinds.get(piece.kind)
    return kind is not None and kind.format == "measurements" and not kind.outside and not piece.outside
