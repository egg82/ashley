"""A bench as her tools show it to the model: ids, kinds, titles, versions and places, each body cut to length here,
with the cut said in a field so she never takes the start of a body for all of it."""

import json
from datetime import tzinfo

from ..stamp import stamp
from ..workshop import reader, recipe, stored_file
from ..workshop.commands import type_of
from ..workshop.model import Piece
from ..workshop.rules import Rules
from ..workshop.workshop import BenchView, Logged


def overview(view: BenchView, rules: Rules, body_chars: int, recent: int, zone: tzinfo | None) -> dict[str, object]:
    """The bench, every piece with its body cut to `body_chars`, its latest `recent` commands oldest first,
    each with when it was decided (`at`) and each piece with when it last changed (`changed_at`), both stamped in
    `zone` (left out when `zone` is None); how many pieces its shelf holds (`bench_shelf` lists them), and the kinds a piece may be, with each one's longest body."""
    return {"bench": view.bench.id, "title": view.bench.title, "closed": view.bench.closed_at is not None,
            "pieces": [{**piece(p, rules, body_chars, changed_at=changed_at(view, p, zone)), "last_changed_by": last_changed_by(view, p)} for p in view.pieces],
            "recent": [_logged(row, zone) for row in view.recent[-recent:]], "undo_next": view.undo_next,
            "shelved": len(view.shelf),
            "kinds": {k.name: {"label": k.label, "max_chars": k.max_chars} for k in rules.kinds.values()}}


def last_changed_by(view: BenchView, p: Piece) -> str:
    """Who last changed the piece, as bench_read says it: `you`, or `person` (a person's latest add, edit, move,
    archive or restore of it), so she can tell a layout she made from one they set."""
    change = view.changes.get(p.id)
    return "you" if change is None or change.by.person_id is None else "person"


def piece(p: Piece, rules: Rules, body_chars: int, offset: int = 0, changed_at: str | None = None,
          text: str | None = None) -> dict[str, object]:
    """One piece, the window of its body from character `offset` of at most `body_chars`; `body_chars` is how long the
    whole body is and `body_cut` whether more of it follows the window. A reader piece's body is the page's text, with
    its `url` and the page's `page_title` beside it. A recipe piece's body is its recipe as text, scaled for its
    headcount in code (`workshop.recipe.text_of`). An image or file piece's body is its name, size and media type; `text`,
    when given, is the text of a text file piece, which replaces it. `changed_at`, when given, is when it last changed."""
    body, page = _shown(p, rules)
    body = body if text is None else text
    return {"id": p.id, "kind": p.kind, "title": p.text.title, "version": p.version, "order": p.place.order,
            "size": p.place.size, "body": body[offset:offset + body_chars], "offset": offset,
            "body_chars": len(body), "body_cut": len(body) > offset + body_chars,
            **({} if page is None else {"url": page.url, "page_title": page.title}),
            **({} if changed_at is None else {"changed_at": changed_at})}


def page_of(read: tuple[int, str] | None) -> dict[str, object]:
    """The fields a site or video piece's read gains: the text of the page it shows and the `result` number a piece is
    added from, or `page_unavailable` when that page could not be read."""
    return {"page_unavailable": True} if read is None else {"result": read[0], "page_text": read[1]}


def _shown(p: Piece, rules: Rules) -> tuple[str, reader.Page | None]:
    """The body she reads for `p`, and the page it came from when `p` is a reader piece holding one."""
    kind = rules.kinds.get(p.kind)
    if kind is not None and kind.family == "large":
        return _described(p.text.body), None
    found = recipe.recipe_of(p.text.body) if kind is not None and kind.format == "recipe" else None
    if found is not None:
        return recipe.text_of(found), None
    page = reader.page_of(p.text.body) if kind is not None and kind.format == "reader" else None
    return (p.text.body if page is None else page.text), page


def _described(body: str) -> str:
    """A large piece's body as she reads it: the file's name, size and media type, never its hash."""
    file = stored_file.file_of(body)
    return body if file is None else json.dumps({"name": file.name, "size": file.size, "media_type": file.media_type},
                                                ensure_ascii=False)


def shelf(view: BenchView) -> dict[str, object]:
    """The bench's shelf, the most recently archived first: each piece's id, kind, title and version, no body."""
    return {"bench": view.bench.id, "shelf": [{"id": p.id, "kind": p.kind, "title": p.text.title, "version": p.version}
                                              for p in view.shelf]}


def changed_at(view: BenchView, p: Piece, zone: tzinfo | None) -> str | None:
    """When `p` last changed, None when the view or the zone does not say."""
    change = view.changes.get(p.id)
    return None if change is None or zone is None else stamp(change.at, zone)


def _logged(row: Logged, zone: tzinfo | None) -> dict[str, object]:
    return {**({} if zone is None else {"at": stamp(row.at, zone)}), "seq": row.seq, "type": type_of(row.command),
            "by": "you" if row.by.person_id is None else "person", "outcome": row.outcome, "piece_id": row.piece_id}
