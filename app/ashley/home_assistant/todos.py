"""Home Assistant's `todo` entities behind the Todos port: the household's lists (`House.states`) and the services
`todo.get_items`, `todo.add_item`, `todo.update_item` and `todo.remove_item`, run through the house as `house_ask` runs
them, over the one client `Homes` keeps. Only here are its field names read."""

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from .. import services
from ..connections.model import Opened
from ..todos.model import Change, TodoItem, TodoList, TodosFailed
from ..todos.source import TodoSource
from .calendars import moment
from .ha_json import JsonObject, is_list, obj, rows
from .homes import Homes, HomesUnavailable
from .house import House, HouseRejected, HouseUnavailable

NAME = "home_assistant"
TEXT_CHARS = 200
_STATUS = {"done": "completed", "reopen": "needs_action"}


async def _house(opened: Opened) -> House | None:
    try:
        home = await services.get(Homes).of(opened.connection.household_id)
    except HomesUnavailable as e:
        raise TodosFailed("unreachable") from e
    return None if home is None else home.house


class HaTodos(TodoSource):
    async def lists(self, opened: Opened) -> tuple[TodoList, ...]:
        house = await _house(opened)
        if house is None:
            return ()
        try:
            states = await house.states()
        except HouseUnavailable as e:
            raise TodosFailed("unreachable") from e
        return tuple(TodoList(s.id, s.name, NAME, opened.connection.id) for s in states if s.domain == "todo")

    async def items(self, opened: Opened, lists: tuple[TodoList, ...]) -> tuple[TodoItem, ...]:
        house = await _house(opened)
        if house is None:
            return ()
        ids = tuple(t.id for t in lists)
        done = await _perform(house, "todo.get_items", ids, {})
        found = parse(done, ids)
        if found is None:
            raise TodosFailed("unrecognised")
        return tuple(found)

    async def change(self, opened: Opened, todo_list: TodoList, change: Change) -> None:
        house = await _house(opened)
        if house is None:
            raise TodosFailed("unreachable")
        await _perform(house, *_call(change, todo_list.id))


def _call(change: Change, list_id: str) -> tuple[str, tuple[str, ...], dict[str, Any]]:
    ids = (list_id,)
    if change.op == "add":
        data: dict[str, Any] = {"item": change.item}
        if change.due is not None:
            data["due_datetime" if isinstance(change.due, datetime) else "due_date"] = change.due.isoformat()
        return "todo.add_item", ids, data
    if change.op == "remove":
        return "todo.remove_item", ids, {"item": [change.item]}
    return "todo.update_item", ids, {"item": change.item, "status": _STATUS[change.op]}


async def _perform(house: House, action: str, ids: tuple[str, ...], data: Mapping[str, Any]) -> Mapping[str, Any] | None:
    try:
        return (await house.perform(action, ids, data)).response
    except HouseRejected as e:
        raise TodosFailed("refused") from e
    except HouseUnavailable as e:
        raise TodosFailed("unreachable") from e


def parse(response: Mapping[str, Any] | None, lists: tuple[str, ...]) -> list[TodoItem] | None:
    """The items of `lists` in a `todo.get_items` response; None when it is not that shape."""
    if response is None:
        return None
    out: list[TodoItem] = []
    for entity in lists:
        held = obj(response.get(entity)).get("items")
        if not is_list(held):
            return None
        for row in rows(held):
            item = _item(row, entity)
            if item is None:
                return None
            out.append(item)
    return out


def _item(row: JsonObject, entity: str) -> TodoItem | None:
    summary, status, uid = row.get("summary"), row.get("status"), row.get("uid")
    if not isinstance(summary, str) or status not in ("needs_action", "completed"):
        return None
    return TodoItem(uid if isinstance(uid, str) else None, summary.strip()[:TEXT_CHARS], status == "completed",
                    moment(row.get("due")), entity)
