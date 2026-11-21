"""The Todos port wired: every connection serving `todo` (`ashley.connections.ports.opened_all`, which honours the
household's switches) is read by the adapter of its kind, and what they hold is combined, each list labelled with its
source. A connection of a kind with no adapter is skipped; a source that fails is `unread`, so one service being down
never hides the others, nor reads as an empty list."""

import logging
import time
from collections.abc import Mapping

from .. import logs, services
from ..connections import ports
from ..connections.connections import Connections, ConnectionsUnavailable
from ..connections.model import Opened
from .model import Board, Change, NoSuchList, NotConnected, TodoItem, TodoList, TodosFailed, TodosUnavailable
from .source import TodoSource
from .todos import Todos

log = logging.getLogger("ashley.todos")


class RoutedTodos(Todos):
    def __init__(self, adapters: Mapping[str, TodoSource]) -> None:
        self._adapters = dict(adapters)

    async def _serving(self, household_id: int) -> list[Opened]:
        try:
            found = await ports.opened_all(services.get(Connections), "todo", household_id)
        except ConnectionsUnavailable as e:
            raise TodosUnavailable from e
        return [o for o in found if o.connection.kind in self._adapters]

    async def connected(self, household_id: int) -> bool:
        return bool(await self._serving(household_id))

    async def board(self, household_id: int, only: tuple[str, ...] | None = None) -> Board:
        began = time.monotonic()
        serving = await self._serving(household_id)
        if not serving:
            raise NotConnected
        lists: list[TodoList] = []
        items: list[TodoItem] = []
        unread: list[str] = []
        for opened in serving:
            kind = opened.connection.kind
            try:
                found = await self._adapters[kind].lists(opened)
                chosen = tuple(t for t in found if only is None or t.id in only)
                items.extend(await self._adapters[kind].items(opened, chosen) if chosen else ())
            except TodosFailed as e:
                logs.warning(log, "todo.unread", source=kind, connection=opened.connection.id, reason=e.reason)
                unread.append(kind)
                continue
            lists.extend(chosen)
        logs.info(log, "todo.read", sources=len(serving), lists=len(lists), items=len(items), unread=len(unread),
                  duration_ms=int((time.monotonic() - began) * 1000))
        return Board(tuple(lists), tuple(items), tuple(unread))

    async def change(self, household_id: int, list_id: str, change: Change) -> None:
        began = time.monotonic()
        serving = await self._serving(household_id)
        if not serving:
            raise NotConnected
        failed: TodosFailed | None = None
        for opened in serving:
            kind = opened.connection.kind
            try:
                held = next((t for t in await self._adapters[kind].lists(opened) if t.id == list_id), None)
                if held is None:
                    continue
                await self._adapters[kind].change(opened, held, change)
            except TodosFailed as e:
                logs.warning(log, "todo.change_failed", op=change.op, source=kind, connection=opened.connection.id,
                             reason=e.reason)
                failed = e
                continue
            logs.info(log, "todo.change", op=change.op, source=kind, duration_ms=int((time.monotonic() - began) * 1000))
            return
        if failed is not None:
            raise failed
        raise NoSuchList
