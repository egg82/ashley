"""The household's to-do lists, read and changed through the Todos port (`ashley.todos.todos`) as her `todo_lists` and
`todo_change` tools (`todo_specs`). Offered per turn by `ashley.channels.turn_tools.sources` to a known speaker, in any
chat, as the house's own reads and list changes are. A household with no to-do source is offered none. Tool arguments
and results are never logged; `tools.call` carries the tool, outcome and row count."""

import time

from .. import services
from ..inference.model import ToolCall, ToolResult
from ..todos.model import NoSuchList, NotConnected, TodosFailed, TodosUnavailable
from ..todos.todos import Todos
from . import bench_results, todo_render
from .todo_specs import CHANGE, INSTRUCTIONS, ITEMS_MAX, LISTS, edit, lists_query, specs
from .tools import Catalogue, Tools, ToolsUnavailable

_UNAVAILABLE = "the household's connections cannot be read"
_NOT_CONNECTED = "the household has no to-do list connected, or has switched to-do lists off"


class TodoTools(Tools):
    def __init__(self, household_id: int) -> None:
        self._household_id = household_id

    async def catalogue(self) -> Catalogue:
        """No tools when the household has no to-do source. Raises ToolsUnavailable when its link cannot be read."""
        try:
            served = await services.get(Todos).connected(self._household_id)
        except TodosUnavailable as e:
            raise ToolsUnavailable("to-do lists unavailable") from e
        return Catalogue(specs(), INSTRUCTIONS) if served else Catalogue((), None)

    async def call(self, call: ToolCall) -> ToolResult:
        """Never raises: an unknown tool, bad arguments, no source, or a source failing are each an error result."""
        started = time.monotonic()
        if call.name == LISTS:
            return await self._lists(call, started)
        if call.name == CHANGE:
            return await self._change(call, started)
        return bench_results.failed(call, started, "unknown_tool", f"no tool named {call.name}")

    async def _lists(self, call: ToolCall, started: float) -> ToolResult:
        query = lists_query(dict(call.arguments))
        if isinstance(query, str):
            return bench_results.failed(call, started, "bad_arguments", query)
        try:
            found = await services.get(Todos).board(self._household_id, None if query.list is None else (query.list,))
        except TodosUnavailable:
            return bench_results.failed(call, started, "unavailable", _UNAVAILABLE)
        except NotConnected:
            return bench_results.failed(call, started, "not_connected", _NOT_CONNECTED)
        if query.list is not None and not found.lists and not found.unread:
            return bench_results.failed(call, started, "bad_arguments",
                                        "list is not a list of the household; todo_lists lists them")
        shown = todo_render.board(found, query.status, ITEMS_MAX)
        return bench_results.ok(call, started, shown, rows=len(found.items))

    async def _change(self, call: ToolCall, started: float) -> ToolResult:
        made = edit(dict(call.arguments))
        if isinstance(made, str):
            return bench_results.failed(call, started, "bad_arguments", made)
        try:
            await services.get(Todos).change(self._household_id, made.list, made.change)
        except TodosUnavailable:
            return bench_results.failed(call, started, "unavailable", _UNAVAILABLE)
        except NotConnected:
            return bench_results.failed(call, started, "not_connected", _NOT_CONNECTED)
        except NoSuchList:
            return bench_results.failed(call, started, "bad_arguments",
                                        "list is not a list of the household; todo_lists lists them")
        except TodosFailed as e:
            return bench_results.failed(call, started, e.reason, "the service did not make the change")
        return bench_results.ok(call, started, {"done": True, "op": made.change.op}, outside=False, rows=1)
