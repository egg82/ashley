"""What the to-do tool answers, made compact from the neutral records (`ashley.todos.model`): only the fields a record
has, `done` only when true, and `cut` true when more items matched than shown."""

from datetime import datetime

from ..todos.model import Board, TodoItem


def _row(item: TodoItem) -> dict[str, object]:
    due = None if item.due is None else item.due.isoformat(timespec="minutes") if isinstance(item.due, datetime) \
        else item.due.isoformat()
    row: dict[str, object | None] = {"summary": item.summary, "id": item.id, "done": item.done or None, "due": due,
                                     "list": item.list_id}
    return {k: v for k, v in row.items() if v is not None}


def board(found: Board, wanted: str, limit: int) -> dict[str, object]:
    """`wanted` is `open`, `done` or `all`."""
    shown = [i for i in found.items if wanted == "all" or i.done == (wanted == "done")]
    out: dict[str, object] = {
        "lists": [{"id": t.id, "title": t.title, "source": t.source} for t in found.lists],
        "items": [_row(i) for i in shown[:limit]], "cut": len(shown) > limit}
    if found.unread:
        out["unread"] = list(found.unread)
    return out
