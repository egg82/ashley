"""`show_card`: she puts a card up beside her words when a person asks to see something, by its kind and the id the
kind's own read names it by (`receipts.Shown`). Her read tools already bring up what they return (`ToolResult.shown`);
this is for a thing she knows without reading it again. A `person` card is the speaker's own, always offered, and
refused for anyone else's id; a `printer` is offered only while the household has a printing manager, and its ref is
checked against that kind's read, so a card never names a thing the household does not have."""

import time
from dataclasses import replace

from .. import services
from ..inference.model import ToolCall, ToolResult, ToolSpec
from ..printing.model import NotConnected, PrintingFailed, PrintingUnavailable
from ..printing.printing import Printing
from ..receipts import Shown
from . import bench_results
from .printing_config import PrintingConfig
from .tools import Catalogue, Tools

SHOW = "show_card"
_INSTRUCTIONS = ("When a person asks to see something you can show as a card (what you know about them, a printer), "
                 "show_card puts it beside your reply. Reading a printer with the printing tools already shows its "
                 "card, so call show_card only when you have not read it this turn. A person card is the one you are "
                 "talking to: its ref is their own person id, and you cannot show anyone else's.")


def _spec(kinds: list[str]) -> ToolSpec:
    parameters: dict[str, object] = {"type": "object", "properties": {
        "kind": {"type": "string", "enum": kinds},
        "ref": {"type": "string", "description": "the thing's id, as its read tool gives it"}},
        "required": ["kind", "ref"]}
    return ToolSpec(SHOW, "Put a card beside your reply showing one thing live: a printer, by the id printing_printers "
                    "gives, or what you know about the person you are talking to (kind person, ref their person id).",
                    parameters, reads=True, outside=False)


class ShowCardTools(Tools):
    def __init__(self, household_id: int, config: PrintingConfig, person_id: int) -> None:
        self._household_id = household_id
        self._person_id = person_id
        self._config = config

    async def catalogue(self) -> Catalogue:
        """The tool, offering a person card always and a printer while the household has a printing manager, which
        printing being unreadable counts as not having."""
        try:
            connected = await services.get(Printing).connected(self._household_id)
        except PrintingUnavailable:
            connected = False
        return Catalogue((_spec(["person", "printer"] if connected else ["person"]),), _INSTRUCTIONS)

    async def call(self, call: ToolCall) -> ToolResult:
        """Never raises: an unknown tool, a kind or ref it cannot show, or the read failing are each an error result."""
        started = time.monotonic()
        if call.name != SHOW:
            return bench_results.failed(call, started, "unknown_tool", f"no tool named {call.name}")
        kind, ref = call.arguments.get("kind"), call.arguments.get("ref")
        if kind == "person" and ref == str(self._person_id):
            return replace(bench_results.ok(call, started, {"shown": "person"}), shown=(Shown("person", str(self._person_id)),))
        if kind == "person":
            return bench_results.failed(call, started, "bad_arguments", "a person card is the speaker's own")
        if kind != "printer" or not isinstance(ref, str):
            return bench_results.failed(call, started, "bad_arguments", "kind is person or printer, and ref its id")
        return await self._printer(call, started, ref)

    async def _printer(self, call: ToolCall, started: float, ref: str) -> ToolResult:
        try:
            page = await services.get(Printing).printers(self._household_id, self._config.printers_max)
        except NotConnected:
            return bench_results.failed(call, started, "not_connected", "the household has not connected a printer")
        except (PrintingFailed, PrintingUnavailable):
            return bench_results.failed(call, started, "unavailable", "the printers cannot be read right now")
        found = next((p for p in page.rows if p.id == ref), None)
        if found is None:
            return bench_results.failed(call, started, "bad_arguments", "no printer has that id; see printing_printers")
        got = bench_results.ok(call, started, {"shown": "printer", "name": found.name})
        return replace(got, shown=(Shown("printer", found.id),))
