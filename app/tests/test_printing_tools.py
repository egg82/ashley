"""Her printing and stock tools (`tools.printing.PrintingTools`, `tools.stock_tools.StockTools`) against a fake Bambuddy:
nothing offered to a household with no connection; each read answers compactly, saying when it was cut; bad arguments ask
Bambuddy nothing; Bambuddy failing is an error result, never a raise; each tool's `outside` is what the PR argues; and the
tools are offered to a known speaker in any chat."""

import asyncio
import json
from collections.abc import Iterator
from dataclasses import replace
from typing import Any

import pytest
from ashley import services
from ashley.api import chat
from ashley.api.models import ChatRequest
from ashley.bambuddy.client import Bambuddy
from ashley.bambuddy.printing import BambuddyPrinting
from ashley.bambuddy.stock import BambuddyStock
from ashley.channels.model import Inbound
from ashley.channels.turn_tools import sources
from ashley.connections.connections import Connections
from ashley.inference.model import ToolCall, ToolResult
from ashley.people.model import Person
from ashley.printing.printing import Printing
from ashley.signin.model import SignedIn
from ashley.stock.stock import Stock
from ashley.tools import printing_config
from ashley.tools.printing import PrintingTools
from ashley.tools.printing_specs import AMS, FILES, NAMES, NEEDS, PRINTERS
from ashley.tools.stock_tools import SPOOLS, StockTools
from ashley.tools.tools import ToolsUnavailable
from bambuddy_support import KEY, FakeBambuddy, held
from money_support import HeldConnections

HOME = 10
CONFIG = printing_config.load()


@pytest.fixture
def fake() -> Iterator[FakeBambuddy]:
    found = FakeBambuddy()
    services.register(Connections, held(HOME))
    services.register(Bambuddy, found.client())
    services.register(Printing, BambuddyPrinting())
    services.register(Stock, BambuddyStock())
    yield found


def call(name: str, arguments: dict[str, object] | None = None, household: int = HOME) -> ToolResult:
    tools = StockTools(household, CONFIG) if name == SPOOLS else PrintingTools(household, CONFIG)
    return asyncio.run(tools.call(ToolCall("c1", name, arguments or {})))


def body(result: ToolResult) -> dict[str, Any]:
    assert not result.is_error, result.content
    loose: dict[str, Any] = json.loads(result.content)
    return loose


def test_a_household_with_no_connection_is_offered_nothing(fake: FakeBambuddy) -> None:
    for tools in (PrintingTools(HOME + 1, CONFIG), StockTools(HOME + 1, CONFIG)):
        assert asyncio.run(tools.catalogue()).specs == ()
    assert call(PRINTERS, household=HOME + 1).content.startswith("not_connected")
    assert call(SPOOLS, household=HOME + 1).content.startswith("not_connected")


def test_the_catalogue_names_five_tools_and_classifies_each(fake: FakeBambuddy) -> None:
    specs = asyncio.run(PrintingTools(HOME, CONFIG).catalogue()).specs + asyncio.run(
        StockTools(HOME, CONFIG).catalogue()).specs
    assert {s.name: (s.reads, s.outside) for s in specs} == {
        PRINTERS: (True, True), AMS: (True, False), FILES: (True, True), NEEDS: (True, True), SPOOLS: (True, True)}
    assert {s.name for s in specs[:4]} == set(NAMES)


def test_a_link_that_cannot_be_read_is_unavailable(fake: FakeBambuddy) -> None:
    down = held(HOME)
    down.down = True
    services.register(Connections, down)
    with pytest.raises(ToolsUnavailable):
        asyncio.run(PrintingTools(HOME, CONFIG).catalogue())
    assert call(PRINTERS).content.startswith("unavailable")


def test_the_printers_answer_is_compact(fake: FakeBambuddy) -> None:
    got = body(call(PRINTERS))
    assert got["cut"] is False
    [printer] = got["printers"]
    assert printer == {"id": "1", "name": "Shed X1C", "model": "X1C", "online": True, "state": "RUNNING", "print": "Benchy",
                       "percent": 42.0, "minutes_left": 95, "layer": 80, "layers": 190,
                       "problems": [{"code": "0300_0100_0002_0001", "text": "Heatbed temperature abnormal"}]}


def test_the_ams_answer_has_each_slot_the_humidity_and_the_recorded_spool(fake: FakeBambuddy) -> None:
    [printer] = body(call(AMS))["printers"]
    [unit] = printer["units"]
    assert (printer["printer"], unit["unit"], unit["humidity"]) == ("Shed X1C", 1, 3)
    assert unit["slots"] == [
        {"slot": 1, "material": "PLA", "colour": "#FF0000", "percent_left": 80, "spool_id": "7"},
        {"slot": 2, "material": "PETG", "colour": "#00FF00"}, {"slot": 3, "empty": True},
        {"slot": 4, "material": "PLA", "colour": "#FFFFFF", "percent_left": 55}]
    assert "Benchy" not in json.dumps(printer)


def test_the_stock_answer_names_what_is_left(fake: FakeBambuddy) -> None:
    got = body(call(SPOOLS))
    assert got["cut"] is False
    assert got["spools"][0] == {"id": "10", "material": "PLA", "brand": "Acme", "colour_name": "Red",
                                "grams_left": 1000, "grams_full": 1000}


def test_the_files_are_searched_and_say_when_cut(fake: FakeBambuddy) -> None:
    got = body(call(FILES, {"search": "benchy", "limit": 1}))
    assert (got["matched"], got["cut"], [f["name"] for f in got["files"]]) == (2, True, ["Benchy Boat Mk2"])
    assert body(call(FILES))["cut"] is False


def test_a_files_needs_and_an_unknown_file(fake: FakeBambuddy) -> None:
    assert body(call(NEEDS, {"file_id": "2"})) == {"filaments": [
        {"slot": 1, "type": "PLA", "colour": "#FF0000", "grams": 10.5},
        {"slot": 2, "type": "PETG", "colour": "#00FF00", "grams": 2.0}]}
    assert call(NEEDS, {"file_id": "99"}).content.startswith("bad_arguments")


@pytest.mark.parametrize(("name", "arguments"), [
    (FILES, {"search": "  "}), (FILES, {"search": "x" * 101}), (FILES, {"limit": 0}), (FILES, {"limit": 101}),
    (FILES, {"limit": True}), (NEEDS, {}), (NEEDS, {"file_id": "../x"}), (NEEDS, {"file_id": 2})])
def test_bad_arguments_ask_bambuddy_nothing(fake: FakeBambuddy, name: str, arguments: dict[str, object]) -> None:
    got = call(name, arguments)
    assert got.is_error and got.content.startswith("bad_arguments") and fake.seen == []


@pytest.mark.parametrize(("status", "outcome"), [(401, "refused"), (500, "unreachable")])
def test_bambuddy_failing_is_an_error_result_without_the_key(status: int, outcome: str, fake: FakeBambuddy) -> None:
    services.register(Bambuddy, FakeBambuddy(status=status).client())
    for name in (PRINTERS, AMS, FILES, SPOOLS):
        got = call(name)
        assert got.is_error and got.content.startswith(outcome) and KEY not in got.content


def test_an_unknown_tool_is_an_error(fake: FakeBambuddy) -> None:
    assert call("printing_start").content.startswith("unknown_tool")
    assert asyncio.run(StockTools(HOME, CONFIG).call(ToolCall("c", "printing_printers", {}))).content.startswith(
        "unknown_tool")


def named(inbound: Inbound) -> set[str]:
    return set(sources(inbound))


def test_the_tools_are_offered_to_a_known_speaker_in_any_chat(fake: FakeBambuddy) -> None:
    alana = Person(1, HOME, "Alana")
    web = chat.inbound_from(SignedIn(3, alana), ChatRequest(text="what's printing?"))
    satellite = Inbound(household_id=HOME, thread="device:7", text="what's printing?", kind="command", medium="spoken",
                        audience="present", speaker_id=1, shared=True, place="kitchen", channel="voice", heard_as=1)
    assert {"printing", "stock"} <= named(web) and {"printing", "stock"} <= named(satellite)
    assert "money" not in named(satellite)
    assert {"print_queue", "print_upload"} & named(satellite) == set() and {"print_queue"} <= named(web)


def test_the_queue_is_offered_where_the_reply_is_theirs_alone_and_the_upload_only_on_a_bench(fake: FakeBambuddy) -> None:
    web = chat.inbound_from(SignedIn(3, Person(1, HOME, "Alana")), ChatRequest(text="queue it"))
    assert "print_queue" in named(web) and "print_upload" not in named(web)
    on_bench = replace(web, bench_id=5)
    assert {"print_queue", "print_upload"} <= named(on_bench)


def test_they_are_not_offered_without_the_apps_key() -> None:
    web = chat.inbound_from(SignedIn(3, Person(1, HOME, "Alana")), ChatRequest(text="x"))
    assert not services.get(Connections).can_open()
    assert not {"printing", "stock"} & named(web)
    services.register(Connections, HeldConnections())
    assert {"printing", "stock"} <= named(web)
