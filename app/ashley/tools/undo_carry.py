"""Carrying out one `Undo` for a person, through the tool that would make that change if they asked her for it, under
that tool's own checks (`decisions.md`, "What she did on her own is one record"): `house_change` (so a delete is judged
by `irreversible.json` and, as shipped, proposed for their yes rather than made), `cancel_reminder`, `todo_change` and
`printing_cancel`. Nothing here writes to the house, the reminders, a list or the print queue itself. Before each, a
read through the same service says whether the target is still there, so a thing already gone comes back as `gone` and
no call is made; the print manager makes that check itself as it cancels, so a print already started is `gone` there.
A delete is made in a turn the caller stores (`Opened`), and agreed by a later turn of the person's, as any delete she
proposes is."""

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

from .. import services
from ..home_assistant.homes import Homes, HomesUnavailable
from ..home_assistant.house import House, HouseUnavailable, config_kind, record_kind
from ..inference.model import ToolCall, ToolResult
from ..senses.wakes import Wakes, WakesUnavailable
from ..todos.model import NotConnected, Op, TodoItem, TodosUnavailable
from ..todos.todos import Todos
from ..undo import Undo
from . import house_change, printing_queue_specs, reminder_specs, todo_specs
from .house_change import HouseChangeTools
from .printing_config import load as printing_config
from .printing_queue import PrintQueueTools
from .reminders import ReminderTools
from .todo_tools import TodoTools
from .tools import ToolsUnavailable

CALL_ID = "undo"
Outcome = Literal["undone", "waiting_on_you", "gone"]
Opened = Callable[[], Awaitable[tuple[int, int]]]
"""Stores the turn a delete is proposed in: its conversation and turn ids."""
_TODO_OP: dict[str, Op] = {"todo_remove": "remove", "todo_reopen": "reopen", "todo_done": "done"}


class UndoFailed(Exception):
    """The tool refused or failed the change, or the undo names nothing it can act on; nothing was undone."""


class UndoUnavailable(Exception):
    """A system the undo reads or goes through could not be reached; nothing was undone."""


@dataclass(frozen=True)
class Carried:
    """How an undo ended: `outcome`, and for `waiting_on_you` the conversation the proposal waits in."""

    outcome: Outcome
    conversation_id: int | None = None


async def carry(undo: Undo, household_id: int, person_id: int, opened: Opened) -> Carried:
    """`undo` carried out for `person_id` of `household_id`; `opened` is called only for a delete, which is proposed in
    the turn it stores. Raises UndoFailed, UndoUnavailable, and whatever `opened` raises."""
    try:
        if undo.kind == "house_delete":
            return await _house(undo, household_id, person_id, opened)
        if undo.kind == "reminder_cancel":
            return await _reminder(undo, household_id, person_id)
        if undo.kind == "print_cancel":
            return await _print(undo, household_id)
        return await _todo(undo, household_id)
    except (HomesUnavailable, HouseUnavailable, WakesUnavailable, TodosUnavailable, ToolsUnavailable) as e:
        raise UndoUnavailable(type(e).__name__) from e


async def _house(undo: Undo, household_id: int, person_id: int, opened: Opened) -> Carried:
    """`house_change` delete of what she created, in a turn the caller stores: the tool judges it as any delete she is
    asked for, so as shipped it is proposed, and agreed by their yes in that conversation."""
    home = await services.get(Homes).of(household_id)
    if home is None or undo.within is None:
        raise UndoFailed("no house, or no kind to delete")
    if not await _there(home.house, undo.within, undo.ref):
        return Carried("gone")
    turn = await opened()
    tools = HouseChangeTools(household_id, person_id, private=True, turn=turn)
    got = _succeeded(await tools.call(ToolCall(CALL_ID, house_change.CHANGE,
                                               {"op": "delete", "kind": undo.within, "id": undo.ref})))
    return Carried("undone") if json.loads(got.content).get("done") is True else Carried("waiting_on_you", turn[0])


async def _there(house: House, kind: str, ref: str) -> bool:
    """Whether the house still has the config or record `ref` of `kind`. Raises UndoFailed for a kind it has neither
    of, HouseUnavailable."""
    config, record = config_kind(kind), record_kind(kind)
    if config is not None:
        return ref in {i.id for i in await house.configs(config)}
    if record is not None:
        return ref in {r.id for r in await house.records(record)}
    raise UndoFailed("not a kind of thing the house keeps")


async def _reminder(undo: Undo, household_id: int, person_id: int) -> Carried:
    """`cancel_reminder` of the reminder, when it is still to fire and theirs (for them or made by them)."""
    if not undo.ref.isdigit():
        raise UndoFailed("not a reminder id")
    wake_id = int(undo.ref)
    listed = await services.get(Wakes).reminders(household_id, person_id)
    if not any(s.id == wake_id and s.state == "scheduled" for s in listed):
        return Carried("gone")
    tools = ReminderTools(household_id, person_id, private=True)
    _succeeded(await tools.call(ToolCall(CALL_ID, reminder_specs.CANCEL, {"id": wake_id})))
    return Carried("undone")


async def _print(undo: Undo, household_id: int) -> Carried:
    """`printing_cancel` of the queued print; the manager cancels only one nobody has started, else it is `gone`."""
    tools = PrintQueueTools(household_id, printing_config())
    got = _succeeded(await tools.call(ToolCall(CALL_ID, printing_queue_specs.CANCEL, {"item_id": undo.ref})))
    return Carried("undone") if json.loads(got.content).get("outcome") == "cancelled" else Carried("gone")


async def _todo(undo: Undo, household_id: int) -> Carried:
    """`todo_change` of the item back to how it was, when the list still has it in the state the change left it in."""
    op = _TODO_OP.get(undo.kind)
    if op is None or undo.within is None:
        raise UndoFailed("not a to-do undo")
    try:
        board = await services.get(Todos).board(household_id, (undo.within,))
    except NotConnected as e:
        raise UndoFailed("no to-do list connected") from e
    if not any(lst.id == undo.within for lst in board.lists):
        if board.unread:
            raise UndoUnavailable("the list's source did not answer")
        return Carried("gone")
    item = next((i for i in board.items if i.list_id == undo.within and undo.ref in (i.id, i.summary)), None)
    if item is None or not _as_left(item, op):
        return Carried("gone")
    tools = TodoTools(household_id)
    _succeeded(await tools.call(ToolCall(CALL_ID, todo_specs.CHANGE,
                                         {"list": undo.within, "op": op, "item": item.id or item.summary})))
    return Carried("undone")


def _as_left(item: TodoItem, op: Op) -> bool:
    """Whether `item` is as the change being undone left it: ticked for a reopen, open for a done, there for a removal."""
    if op == "reopen":
        return item.done
    if op == "done":
        return not item.done
    return True


def _succeeded(got: ToolResult) -> ToolResult:
    if got.is_error:
        raise UndoFailed("the tool did not make the change")
    return got
