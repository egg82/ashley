"""A household's to-do lists as she sees them, whichever service holds them: plain records whose fields are stated in
to-do terms. An adapter (for Home Assistant, `ashley.home_assistant.todos`) fills them from its service's own shapes;
nothing outside it knows those shapes."""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

Reason = Literal["refused", "unreachable", "unrecognised"]
"""Why a read or change failed: `refused`, the service turned the household's credentials or the request away;
`unreachable`, no answer in time or a server error; `unrecognised`, the answer is not the service's own shape."""

Op = Literal["add", "done", "reopen", "remove"]
"""What a change does to a list: `add` an item, mark one `done` or `reopen` it, `remove` it."""


@dataclass(frozen=True)
class TodoList:
    """One list: `id` is the service's own, `title` what it is called there, `source` the kind of connection that holds
    it and `connection_id` which one."""

    id: str
    title: str
    source: str
    connection_id: int


@dataclass(frozen=True)
class TodoItem:
    """One item of the list `list_id`: `id` is the service's own, None when it gives none, `summary` the text, `done`
    whether it is ticked off, `due` a date or a moment when it has one. `summary` can be written by whoever may add to
    the list."""

    id: str | None
    summary: str
    done: bool
    due: date | datetime | None
    list_id: str


@dataclass(frozen=True)
class Change:
    """One change: `op` on `item`, the id as `TodoItem.id` gives it or the item's exact text (for `add`, the text of the
    new item). `due` is only for `add`."""

    op: Op
    item: str
    due: date | datetime | None = None


@dataclass(frozen=True)
class Board:
    """What the household's lists hold: the `lists` read, their `items` (those asked for) and the `unread` sources
    (connection kinds) that could not be read now, whose lists and items are missing."""

    lists: tuple[TodoList, ...]
    items: tuple[TodoItem, ...]
    unread: tuple[str, ...]


class TodosFailed(Exception):
    def __init__(self, reason: Reason) -> None:
        super().__init__(reason)
        self.reason: Reason = reason


class TodosUnavailable(Exception):
    """The household's connections cannot be read now."""


class NotConnected(Exception):
    """The household has no to-do source switched on."""


class NoSuchList(Exception):
    """No list of the household's serving connections has that id."""
