"""What her tools bring up beside her words (`ToolResult.shown`): a printers read brings up each printer it returned and
no other read does; `show_card` brings up a printer the household has, by its id, and refuses anything else with nothing
brought up; it is offered only while the household has a printing manager, and to a known speaker beside printing."""

import asyncio
from dataclasses import dataclass, field
from typing import Any

import pytest
from ashley import services
from ashley.channels.model import Inbound
from ashley.channels.turn_tools import sources
from ashley.connections.connections import Connections
from ashley.inference.model import ToolCall, ToolResult
from ashley.printing.model import NotConnected, Page, PrintFile, Printer, PrintingFailed
from ashley.printing.printing import NullPrinting, Printing
from ashley.receipts import Shown
from ashley.tools import printing_config
from ashley.tools.printing import PrintingTools
from ashley.tools.printing_specs import AMS, FILES, PRINTERS
from ashley.tools.show_card import SHOW, ShowCardTools
from money_support import HeldConnections

HOME = 10
CONFIG = printing_config.load()


def printer(id_: str) -> Printer:
    return Printer(id_, f"Printer {id_}", None, True, "IDLE", None, None, None, None, None, (), ())


@dataclass
class FakePrinting(NullPrinting):
    rows: tuple[Printer, ...] = (printer("01P"), printer("02X"))
    error: Exception | None = None
    files_found: tuple[PrintFile, ...] = field(default_factory=tuple[PrintFile, ...])

    async def connected(self, household_id: int) -> bool:
        return not isinstance(self.error, NotConnected)

    async def printers(self, household_id: int, limit: int) -> Page[Printer]:
        if self.error is not None:
            raise self.error
        return Page(self.rows, len(self.rows))

    async def files(self, household_id: int, search: str | None, limit: int) -> Page[PrintFile]:
        return Page(self.files_found, len(self.files_found))


@pytest.fixture
def fake() -> FakePrinting:
    found = FakePrinting()
    services.register(Printing, found)
    return found


def run(tools: Any, name: str, arguments: dict[str, object] | None = None) -> ToolResult:
    got: ToolResult = asyncio.run(tools.call(ToolCall("c1", name, arguments or {})))
    return got


def test_a_printers_read_brings_up_each_printer_it_returned(fake: FakePrinting) -> None:
    for name in (PRINTERS, AMS):
        got = run(PrintingTools(HOME, CONFIG), name)
        assert not got.is_error and got.shown == (Shown("printer", "01P"), Shown("printer", "02X")), name


def test_a_read_of_anything_else_or_a_failed_read_brings_up_nothing(fake: FakePrinting) -> None:
    assert run(PrintingTools(HOME, CONFIG), FILES).shown == ()
    fake.error = PrintingFailed("unreachable")
    got = run(PrintingTools(HOME, CONFIG), PRINTERS)
    assert got.is_error and got.shown == ()


def test_show_card_brings_up_a_printer_the_household_has(fake: FakePrinting) -> None:
    got = run(ShowCardTools(HOME, CONFIG), SHOW, {"kind": "printer", "ref": "02X"})
    assert not got.is_error and got.shown == (Shown("printer", "02X"),)


@pytest.mark.parametrize("arguments", [{"kind": "printer", "ref": "nope"}, {"kind": "forecast", "ref": "01P"},
                                       {"kind": "printer"}, {"kind": "printer", "ref": 1}])
def test_show_card_refuses_what_it_cannot_show_and_brings_up_nothing(fake: FakePrinting,
                                                                     arguments: dict[str, object]) -> None:
    got = run(ShowCardTools(HOME, CONFIG), SHOW, arguments)
    assert got.is_error and got.shown == ()


def test_show_card_with_printers_that_cannot_be_read_brings_up_nothing(fake: FakePrinting) -> None:
    fake.error = PrintingFailed("unreachable")
    got = run(ShowCardTools(HOME, CONFIG), SHOW, {"kind": "printer", "ref": "01P"})
    assert got.is_error and got.shown == ()


def test_show_card_is_offered_only_while_the_household_has_a_printing_manager(fake: FakePrinting) -> None:
    assert [s.name for s in asyncio.run(ShowCardTools(HOME, CONFIG).catalogue()).specs] == [SHOW]
    fake.error = NotConnected()
    assert asyncio.run(ShowCardTools(HOME, CONFIG).catalogue()).specs == ()


def test_a_known_speaker_is_offered_show_card_beside_printing(fake: FakePrinting) -> None:
    services.register(Connections, HeldConnections())
    try:
        found = sources(Inbound(household_id=HOME, thread="device:7", text="show me", kind="command", medium="spoken",
                                audience="present", speaker_id=1, shared=True, place="kitchen", channel="voice"))
    finally:
        services.unregister(Connections)
    assert isinstance(found["show"], ShowCardTools) and "printing" in found
