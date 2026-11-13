"""The bench as it stood when a turn began, as text for the `moment` layer of her prompt (`Catalogue.now`): household
words only. A piece of an outside kind, or one a turn that had read outside words wrote, shows its id, kind and version
and nothing else, so the view never carries outside words and never taints a turn; `bench_read_piece` reads such a piece,
tainting as it always did."""

import json

OPEN_HEAD = ("\nStill open on this bench: the guessed rows of its facts, numbers and choices, each still to settle "
             "(shown true on a number: the app has put it in front of the person and they have not answered).")
OUTSIDE_HEAD = ("\nWritten by a turn that read outside words, so shown by id alone: facts pieces with rows still to "
                "settle, each with how many (bench_read_piece reads one, and that taints this turn).")

from ..workshop import facts
from ..workshop.commands import ShownRow
from ..workshop.model import Piece
from ..workshop.rules import Rules
from ..workshop.workshop import BenchView
from .bench_view import last_changed_by, piece


def now(view: BenchView, rules: Rules, body_chars: int) -> str:
    """`view`'s bench and one line of JSON per piece in order: id, kind, title, version, order, size, who last changed it
    and the first `body_chars` of its body with the body's whole length; id, kind and version alone for an outside piece.
    Then every open row (`open_rows`), however far into its piece, so a later turn carries what is still to settle, and
    for each outside facts piece with unconfirmed rows only its id and how many (`outside_open`)."""
    head = f'# The bench as it stood when this turn began\n\nBench {view.bench.id}, "{view.bench.title}".'
    lines = [json.dumps(_line(view, p, rules, body_chars), ensure_ascii=False) for p in view.pieces]
    rows = open_rows(view, rules)
    still = [OPEN_HEAD, *(json.dumps(r, ensure_ascii=False) for r in rows)] if rows else []
    counted = outside_open(view, rules)
    beyond = [OUTSIDE_HEAD, *(json.dumps(c) for c in counted)] if counted else []
    return "\n".join([head, *lines, *still, *beyond])


def open_rows(view: BenchView, rules: Rules) -> list[dict[str, object]]:
    """The rows of the bench's facts pieces that are not confirmed and are household words (neither an outside
    kind nor written by a turn that read outside words): a number with its piece, name, value, unit and whether the
    app has shown it to the person (`BenchView.surfaced`); a choice with its piece, name, `kind`, label and value."""
    found: list[dict[str, object]] = []
    for p in view.pieces:
        kind = rules.kinds.get(p.kind)
        if kind is None or kind.format != "facts" or kind.outside or p.outside:
            continue
        for m in facts.items_of(p.text.body) or ():
            if not facts.confirmed(m):
                found.append(_open(p.id, m, view))
    return found


def outside_open(view: BenchView, rules: Rules) -> list[dict[str, int]]:
    """For each facts piece `open_rows` skips (an outside kind, or written by a turn that read outside words)
    holding rows that are not confirmed: its id and how many, ids and counts only, so the line never taints."""
    found: list[dict[str, int]] = []
    for p in view.pieces:
        kind = rules.kinds.get(p.kind)
        if kind is None or kind.format != "facts" or not (kind.outside or p.outside):
            continue
        count = sum(not facts.confirmed(m) for m in facts.items_of(p.text.body) or ())
        if count:
            found.append({"piece": p.id, "unconfirmed": count})
    return found


def _open(piece_id: int, m: facts.Row, view: BenchView) -> dict[str, object]:
    if isinstance(m, facts.Choice):
        return {"piece": piece_id, "name": m.name, "kind": facts.CHOICE, "label": m.label, "value": m.value}
    return {"piece": piece_id, "name": m.name, "value": m.value, "unit": m.unit,
            "shown": (piece_id, ShownRow(m.name, facts.shown_value(m))) in view.surfaced}


def _line(view: BenchView, p: Piece, rules: Rules, body_chars: int) -> dict[str, object]:
    if rules.shows_outside([p.kind]) or p.outside:
        return {"id": p.id, "kind": p.kind, "version": p.version}
    shown = piece(p, rules, body_chars)
    keep = ("id", "kind", "title", "version", "order", "size", "body", "body_chars", "body_cut")
    return {**{k: shown[k] for k in keep}, "last_changed_by": last_changed_by(view, p)}
