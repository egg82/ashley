"""A print put in the household's queue, through the Printing service (`ashley.printing.printing`), as her
`printing_queue` tool (`printing_queue_specs`). Offered per turn by `ashley.channels.turn_tools.sources` only where the
reply reaches the speaker alone (`ashley.channels.audience.owner_alone`), like the money tools, and not a read: its tier
is `asks`, so every call is held for the person's OK (`ashley.tools.outside`), shown by `shown`, and reaches Bambuddy only
when they agree. The item is always staged, so the person starts it in Bambuddy. A household with no printing manager
is offered none. Tool arguments and results are never logged; `tools.call` carries the tool, outcome and how many were
queued."""

import asyncio
import time

from .. import services
from ..inference.model import ToolCall, ToolResult
from ..printing.model import NotConnected, PrintingFailed, PrintingUnavailable, QueueRequest
from ..printing.printing import Printing
from . import bench_results, printing_render
from .printing_config import PrintingConfig
from .printing_queue_specs import QUEUE, QUEUE_INSTRUCTIONS, queue_request, queue_spec
from .tools import Catalogue, Tools, ToolsUnavailable, Unshown

_UNAVAILABLE = "the household's connections cannot be read"
_NOT_CONNECTED = "the household has not connected Bambuddy"
_REFUSED = ("Bambuddy turned the print away; the household's key may not queue prints, and someone in the household can "
            "replace it in settings with one that may")
_UNREACHABLE = "Bambuddy did not answer; nothing was queued"
_UNEXPECTED = "Bambuddy answered with something unexpected"
_UNSHOWN = "Bambuddy could not be read to show the person what would be queued; nothing was asked or queued"
_NO_FILE = "file_id is not a file in the print library; printing_files lists them"
_NO_PRINTER = "printer_id is not one of the household's printers; printing_printers lists them"
_NO_SLOT = ("slots names an AMS slot the printer does not have or a filament the file does not need; printing_ams and "
            "printing_needs list them")


class PrintQueueTools(Tools):
    def __init__(self, household_id: int, config: PrintingConfig) -> None:
        self._household_id = household_id
        self._config = config
        self._connected: bool | None = None

    async def catalogue(self) -> Catalogue:
        """No tools when the household has no printing manager. Raises ToolsUnavailable when its link cannot be read."""
        if not await self._is_connected():
            return Catalogue((), None)
        return Catalogue((queue_spec(self._config),), QUEUE_INSTRUCTIONS)

    async def call(self, call: ToolCall) -> ToolResult:
        """Never raises: an unknown tool, bad arguments, no manager, or the manager failing are each an error result."""
        started = time.monotonic()
        if call.name != QUEUE:
            return bench_results.failed(call, started, "unknown_tool", f"no tool named {call.name}")
        asked = queue_request(dict(call.arguments), self._config)
        if isinstance(asked, str):
            return bench_results.failed(call, started, "bad_arguments", asked)
        try:
            if not await self._is_connected():
                return bench_results.failed(call, started, "not_connected", _NOT_CONNECTED)
            done = await services.get(Printing).queue(self._household_id, asked)
        except (ToolsUnavailable, PrintingUnavailable):
            return bench_results.failed(call, started, "unavailable", _UNAVAILABLE)
        except NotConnected:
            return bench_results.failed(call, started, "not_connected", _NOT_CONNECTED)
        except PrintingFailed as e:
            outcome, hint = {"refused": ("refused", _REFUSED), "unreachable": ("unreachable", _UNREACHABLE)
                             }.get(e.reason, ("not_bambuddy", _UNEXPECTED))
            return bench_results.failed(call, started, outcome, hint)
        return bench_results.ok(call, started, printing_render.queued(done), rows=int(done.outcome == "queued"))

    async def shown(self, call: ToolCall) -> str | None:
        """For `printing_queue`, what would be queued as the manager holds it now (`printing_render.queuing`); None for
        any other tool. Raises Unshown for wrong arguments, a file, printer, slot or filament that is not there, or a
        manager that cannot be read."""
        if call.name != QUEUE:
            return None
        asked = queue_request(dict(call.arguments), self._config)
        if isinstance(asked, str):
            raise Unshown(asked)
        try:
            return await self._shown(asked)
        except (PrintingFailed, PrintingUnavailable, NotConnected) as e:
            raise Unshown(_UNSHOWN) from e

    async def _shown(self, asked: QueueRequest) -> str:
        printing, household = services.get(Printing), self._household_id
        file, printers, needs = await asyncio.gather(
            printing.file(household, asked.file_id), printing.printers(household, self._config.printers_max),
            printing.needs(household, asked.file_id))
        if file is None:
            raise Unshown(_NO_FILE)
        printer = next((p for p in printers.rows if p.id == asked.printer_id), None)
        if printer is None:
            raise Unshown(_NO_PRINTER)
        line = printing_render.queuing(file, printer, asked, needs or ())
        if line is None:
            raise Unshown(_NO_SLOT)
        return line

    async def _is_connected(self) -> bool:
        if self._connected is None:
            try:
                self._connected = await services.get(Printing).connected(self._household_id)
            except PrintingUnavailable as e:
                raise ToolsUnavailable("printing unavailable") from e
        return self._connected
