"""`show_card`: she puts a card up beside her words when a person asks to see something, by its kind and the id the
kind's own read names it by (`receipts.Shown`). Her read tools already bring up what they return (`ToolResult.shown`);
this is for a thing she knows without reading it again. Offered while some kind has something to show: today a
printer, so only while the household has a printing manager. The ref is checked against that kind's read, so a card
never names a thing the household does not have. Logs `tools.call` with the outcome."""

import time
from dataclasses import replace

from .. import services
from ..inference.model import ToolCall, ToolResult, ToolSpec
from ..printing.model import NotConnected, PrintingFailed, PrintingUnavailable
from ..printing.printing import Printing
from ..receipts import Shown
from . import bench_results
from .printing_config import PrintingConfig
from .tools import Catalogue, Tools, ToolsUnavailable

SHOW = "show_card"
_INSTRUCTIONS = ("When a person asks to see something you can show as a card (a printer), show_card puts it beside "
                 "your reply. Reading a printer with the printing tools already shows its card, so call show_card only "
                 "when you have not read it this turn.")
_SPEC = ToolSpec(SHOW, "Put a card beside your reply showing one thing live: a printer, by the id printing_printers "
                 "gives.", {"type": "object", "properties": {
                     "kind": {"type": "string", "enum": ["printer"]},
                     "ref": {"type": "string", "description": "the thing's id, as its read tool gives it"}},
                     "required": ["kind", "ref"]}, reads=True, outside=False)


class ShowCardTools(Tools):
    def __init__(self, household_id: int, config: PrintingConfig) -> None:
        self._household_id = household_id
        self._config = config

    async def catalogue(self) -> Catalogue:
        """The tool while the household has a printing manager. Raises ToolsUnavailable when that cannot be read."""
        try:
            connected = await services.get(Printing).connected(self._household_id)
        except PrintingUnavailable as e:
            raise ToolsUnavailable("printing unavailable") from e
        return Catalogue((_SPEC,), _INSTRUCTIONS) if connected else Catalogue((), None)

    async def call(self, call: ToolCall) -> ToolResult:
        """Never raises: an unknown tool, a kind or ref it cannot show, or the read failing are each an error result."""
        started = time.monotonic()
        if call.name != SHOW:
            return bench_results.failed(call, started, "unknown_tool", f"no tool named {call.name}")
        kind, ref = call.arguments.get("kind"), call.arguments.get("ref")
        if kind != "printer" or not isinstance(ref, str):
            return bench_results.failed(call, started, "bad_arguments", "kind is printer and ref a printer's id")
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
