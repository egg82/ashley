"""The to-do port and her `todo_lists` and `todo_change` tools over Home Assistant's adapter, against an in-memory house:
nothing is offered to a household with no to-do source or with the port switched off; items come back labelled with their
list and source; a change reaches the house as the service call that makes it; a removal is judged where an add is not;
a source that cannot answer is `unread`, never an empty list; and bad arguments ask the house nothing."""

import asyncio
import json
from collections.abc import Iterator, Mapping
from typing import Any

import pytest
from ashley import services
from ashley.channels.model import Inbound
from ashley.channels.turn_tools import sources
from ashley.connections.connections import Connections
from ashley.connections.model import Port
from ashley.connections.settings import SettingValues
from ashley.connections.settings_read import NullSettingsReader, SettingsReader
from ashley.home_assistant.homes import Homes
from ashley.home_assistant.todos import NAME, HaTodos
from ashley.inference.model import ToolCall, ToolResult
from ashley.todos.routed import RoutedTodos
from ashley.todos.todos import Todos
from ashley.tools import tiers
from ashley.tools.todo_specs import CHANGE, LISTS
from ashley.tools.todo_tools import TodoTools
from ashley.undo import Undo
from homes_support import AnyHousehold
from house_double_support import MemoryHouse, state
from money_support import HeldConnections
from respond_support import HOME

GROCERY, CHORES = "todo.zq_grocery", "todo.zq_chores"


class Switches(NullSettingsReader):
    def __init__(self, off: frozenset[str] = frozenset()) -> None:
        self.off = off

    async def of(self, household_id: int, port: Port) -> SettingValues:
        return {}

    async def ports_off(self, household_id: int) -> Mapping[int, frozenset[str]]:
        return {1: self.off} if self.off else {}


def _item(summary: str, uid: str, status: str = "needs_action", **more: str) -> dict[str, str]:
    return {"summary": summary, "uid": uid, "status": status, **more}


@pytest.fixture
def house() -> Iterator[MemoryHouse]:
    made = MemoryHouse()
    made.things = [state(GROCERY, "Grocery", "2"), state(CHORES, "Chores", "1"), state("light.zq", "Lamp", "on")]
    made.returns["todo.get_items"] = {
        GROCERY: {"items": [_item("Oat milk", "u1"), _item("Rye bread", "u2", "completed", due="2026-11-14")]},
        CHORES: {"items": [_item("Water ferns", "u3", due="2026-11-15T09:30:00")]}}
    held = HeldConnections()
    held.connect(HOME.id, "http://ha.test", "k", NAME)
    services.register(Connections, held)
    services.register(Homes, AnyHousehold(made))
    services.register(Todos, RoutedTodos({NAME: HaTodos()}))
    services.register(SettingsReader, Switches())
    yield made


def run(name: str, arguments: dict[str, object], household: int = HOME.id) -> ToolResult:
    return asyncio.run(TodoTools(household).call(ToolCall("c1", name, arguments)))


def body(result: ToolResult) -> dict[str, Any]:
    assert not result.is_error, result.content
    loose: dict[str, Any] = json.loads(result.content)
    return loose


def test_a_household_with_no_to_do_source_is_offered_nothing(house: MemoryHouse) -> None:
    assert asyncio.run(TodoTools(HOME.id + 1).catalogue()).specs == ()


def test_the_read_is_outside_and_the_change_is_her_own_at_the_runs_tier(house: MemoryHouse) -> None:
    read, change = asyncio.run(TodoTools(HOME.id).catalogue()).specs
    assert (read.name, read.reads, read.outside) == (LISTS, True, True)
    assert (change.name, change.reads, change.outside, change.tier) == (CHANGE, False, False, "runs")


def test_open_items_come_back_labelled_with_their_list_and_source(house: MemoryHouse) -> None:
    got = body(run(LISTS, {}))
    assert got["lists"] == [{"id": GROCERY, "title": "Grocery", "source": NAME},
                            {"id": CHORES, "title": "Chores", "source": NAME}]
    assert got["items"] == [{"summary": "Oat milk", "id": "u1", "list": GROCERY},
                            {"summary": "Water ferns", "id": "u3", "due": "2026-11-15T09:30", "list": CHORES}]
    assert got["cut"] is False and "unread" not in got
    assert house.done[0][2:4] == ("todo.get_items", (GROCERY, CHORES))


def test_done_items_and_one_list_by_id(house: MemoryHouse) -> None:
    house.returns["todo.get_items"] = {GROCERY: house.returns["todo.get_items"][GROCERY]}
    got = body(run(LISTS, {"list": GROCERY, "status": "done"}))
    assert got["items"] == [{"summary": "Rye bread", "id": "u2", "done": True, "due": "2026-11-14", "list": GROCERY}]
    assert house.done[0][3] == (GROCERY,)
    assert run(LISTS, {"list": "todo.nope"}).content.startswith("bad_arguments")


@pytest.mark.parametrize("arguments", [
    {"list": ""}, {"status": "all of them"}, {"list": 4}])
def test_bad_reads_ask_the_house_nothing(house: MemoryHouse, arguments: dict[str, object]) -> None:
    assert run(LISTS, arguments).content.startswith("bad_arguments")
    assert house.done == []


@pytest.mark.parametrize("op, action, data", [
    ("add", "todo.add_item", {"item": "Lemons"}),
    ("done", "todo.update_item", {"item": "u1", "status": "completed"}),
    ("reopen", "todo.update_item", {"item": "u1", "status": "needs_action"}),
    ("remove", "todo.remove_item", {"item": ["u1"]})])
def test_each_change_is_the_service_call_that_makes_it(house: MemoryHouse, op: str, action: str,
                                                       data: dict[str, object]) -> None:
    item = "Lemons" if op == "add" else "u1"
    assert body(run(CHANGE, {"list": GROCERY, "op": op, "item": item})) == {"done": True, "op": op}
    assert house.done[-1][2:] == (action, (GROCERY,), data)


@pytest.mark.parametrize("op, undo", [
    ("add", Undo("todo_remove", "Lemons", GROCERY)), ("done", Undo("todo_reopen", "Lemons", GROCERY)),
    ("reopen", Undo("todo_done", "Lemons", GROCERY)), ("remove", None)])
def test_a_change_carries_the_change_that_takes_it_back_and_a_removal_carries_none(house: MemoryHouse, op: str,
                                                                                    undo: Undo | None) -> None:
    got = run(CHANGE, {"list": GROCERY, "op": op, "item": "Lemons"})
    assert not got.is_error and got.undo == undo
    assert run(CHANGE, {"list": "todo.nope", "op": op, "item": "Lemons"}).undo is None, "a refused change has none"


def test_an_added_item_carries_its_due_day_or_moment(house: MemoryHouse) -> None:
    run(CHANGE, {"list": GROCERY, "op": "add", "item": "Lemons", "due": "2026-11-20"})
    run(CHANGE, {"list": GROCERY, "op": "add", "item": "Limes", "due": "2026-11-20T18:00"})
    assert house.done[0][4] == {"item": "Lemons", "due_date": "2026-11-20"}
    assert house.done[1][4] == {"item": "Limes", "due_datetime": "2026-11-20T18:00:00"}


@pytest.mark.parametrize("arguments", [
    {"op": "add", "item": "x"}, {"list": GROCERY, "op": "rename", "item": "x"}, {"list": GROCERY, "op": "add"},
    {"list": GROCERY, "op": "add", "item": " "}, {"list": GROCERY, "op": "done", "item": "u1", "due": "2026-11-20"},
    {"list": GROCERY, "op": "add", "item": "x", "due": "soon"}])
def test_bad_changes_ask_the_house_nothing(house: MemoryHouse, arguments: dict[str, object]) -> None:
    assert run(CHANGE, arguments).content.startswith("bad_arguments")
    assert house.done == []


def test_a_change_to_a_list_the_household_lacks_is_refused_without_calling_the_house(house: MemoryHouse) -> None:
    assert run(CHANGE, {"list": "todo.nope", "op": "add", "item": "x"}).content.startswith("bad_arguments")
    assert [d[2] for d in house.done] == []


def test_a_house_that_refuses_the_change_is_an_error_result(house: MemoryHouse) -> None:
    house.refuse = "no"
    assert run(CHANGE, {"list": GROCERY, "op": "add", "item": "x"}).content.startswith("refused")


@pytest.mark.parametrize("value", ["unavailable", "unknown"])
def test_a_list_the_house_cannot_read_is_not_offered_or_asked_for(house: MemoryHouse, value: str) -> None:
    house.things.append(state("todo.zz_gone", "Gone", value))
    got = body(run(LISTS, {}))
    assert [entry["id"] for entry in got["lists"]] == [GROCERY, CHORES]
    assert [entry["summary"] for entry in got["items"]] == ["Oat milk", "Water ferns"] and "unread" not in got
    assert house.done[0][3] == (GROCERY, CHORES)


def test_an_available_list_missing_from_the_response_is_still_unread(house: MemoryHouse) -> None:
    house.returns["todo.get_items"] = {GROCERY: house.returns["todo.get_items"][GROCERY]}
    got = body(run(LISTS, {}))
    assert got["unread"] == [NAME] and got["items"] == []


@pytest.mark.parametrize("fault", ["down", "refused", "malformed"])
def test_a_house_that_cannot_say_is_unread_not_empty(house: MemoryHouse, fault: str) -> None:
    house.refuse = "no" if fault == "refused" else None
    if fault == "malformed":
        house.returns["todo.get_items"] = {GROCERY: {"items": "many"}, CHORES: {"items": []}}
    house.down = fault == "down"
    got = body(run(LISTS, {}))
    assert got["unread"] == [NAME] and got["items"] == []


def test_a_port_switched_off_is_as_if_the_connection_did_not_serve_to_do_lists(house: MemoryHouse) -> None:
    services.register(SettingsReader, Switches(frozenset({"todo"})))
    assert asyncio.run(TodoTools(HOME.id).catalogue()).specs == ()
    assert run(LISTS, {}).content.startswith("not_connected")
    assert run(CHANGE, {"list": GROCERY, "op": "add", "item": "x"}).content.startswith("not_connected")
    assert house.done == []


def test_a_connections_link_that_cannot_be_read_is_unavailable(house: MemoryHouse) -> None:
    held = HeldConnections()
    held.down = True
    services.register(Connections, held)
    assert run(LISTS, {}).content.startswith("unavailable")


def test_only_a_removal_is_judged_in_a_tainted_turn() -> None:
    def tier(op: str) -> object:
        return tiers.by_arguments(ToolCall("c", CHANGE, {"list": GROCERY, "op": op, "item": "x"}))
    assert [tier(op) for op in ("add", "done", "reopen", "remove")] == [None, None, None, "judged"]


def test_the_tools_are_offered_to_a_known_speaker_in_any_chat(house: MemoryHouse) -> None:
    satellite = Inbound(household_id=HOME.id, thread="device:7", text="what is on the list?", kind="command",
                        medium="spoken", audience="present", speaker_id=1, shared=True, place="kitchen",
                        channel="voice", heard_as=1)
    assert "todo" in sources(satellite)
