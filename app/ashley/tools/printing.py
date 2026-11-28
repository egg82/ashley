"""The household's printers, AMS slots and print library, read through the Printing service
(`ashley.printing.printing`), as her printing tools (`printing_specs`). Offered per turn by
`ashley.channels.turn_tools.sources` to a known speaker, in any chat: what the printers are doing is the household's, not
one person's. All only read, so none is held for an OK. A household with no printing manager is offered none. Tool
arguments and results are never logged; `tools.call` carries the tool, outcome and row count."""

import time
from collections.abc import Sized
from dataclasses import replace

from .. import services
from ..inference.model import ToolCall, ToolResult
from ..printing.model import NotConnected, PrintingFailed, PrintingUnavailable, Reason
from ..printing.printing import Printing
from ..receipts import Shown
from . import bench_results, printing_render
from .printing_config import PrintingConfig
from .printing_specs import AMS, FILES, INSTRUCTIONS, NAMES, NEEDS, PRINTERS, file_id, files_query, specs
from .tools import Catalogue, Tools, ToolsUnavailable

_FAILED: dict[Reason, tuple[str, str]] = {
    "refused": ("refused", "Bambuddy turned the household's key away, or the key may not read this; someone in the "
                           "household can replace it in settings"),
    "unreachable": ("unreachable", "Bambuddy did not answer"),
    "unrecognised": ("not_bambuddy", "Bambuddy answered with something unexpected")}
_UNAVAILABLE = "the household's connections cannot be read"
_NOT_CONNECTED = "the household has not connected Bambuddy"


class PrintingTools(Tools):
    def __init__(self, household_id: int, config: PrintingConfig) -> None:
        self._household_id = household_id
        self._config = config
        self._connected: bool | None = None

    async def catalogue(self) -> Catalogue:
        """No tools when the household has no printing manager. Raises ToolsUnavailable when its link cannot be read."""
        return Catalogue(specs(self._config), INSTRUCTIONS) if await self._is_connected() else Catalogue((), None)

    async def call(self, call: ToolCall) -> ToolResult:
        """Never raises: an unknown tool, bad arguments, no manager, or the manager failing are each an error result."""
        started = time.monotonic()
        if call.name not in NAMES:
            return bench_results.failed(call, started, "unknown_tool", f"no tool named {call.name}")
        try:
            if not await self._is_connected():
                return bench_results.failed(call, started, "not_connected", _NOT_CONNECTED)
            got = await self._read(call)
        except (ToolsUnavailable, PrintingUnavailable):
            return bench_results.failed(call, started, "unavailable", _UNAVAILABLE)
        except NotConnected:
            return bench_results.failed(call, started, "not_connected", _NOT_CONNECTED)
        except PrintingFailed as e:
            outcome, hint = _FAILED[e.reason]
            return bench_results.failed(call, started, outcome, hint)
        if isinstance(got, str):
            return bench_results.failed(call, started, "bad_arguments", got)
        body, shown = got
        return replace(bench_results.ok(call, started, body, rows=_rows(body)), shown=shown)

    async def _read(self, call: ToolCall) -> tuple[dict[str, object], tuple[Shown, ...]] | str:
        """The result's body and what it brings up beside her words: each printer a printers read returned."""
        printing, household = services.get(Printing), self._household_id
        if call.name in (PRINTERS, AMS):
            page = await printing.printers(household, self._config.printers_max)
            render = printing_render.printers if call.name == PRINTERS else printing_render.ams
            return render(page), tuple(Shown("printer", p.id) for p in page.rows)
        if call.name == FILES:
            query = files_query(dict(call.arguments), self._config)
            if isinstance(query, str):
                return query
            return printing_render.files(await printing.files(household, query.search, query.limit)), ()
        assert call.name == NEEDS
        wanted = file_id(dict(call.arguments))
        if wanted is None:
            return "file_id is an id as printing_files gives it"
        found = await printing.needs(household, wanted)
        if found is None:
            return "file_id is not a file in the print library; printing_files lists them"
        return printing_render.needs(found), ()

    async def _is_connected(self) -> bool:
        if self._connected is None:
            try:
                self._connected = await services.get(Printing).connected(self._household_id)
            except PrintingUnavailable as e:
                raise ToolsUnavailable("printing unavailable") from e
        return self._connected


def _rows(got: dict[str, object]) -> int:
    for key in ("printers", "files", "filaments"):
        rows = got.get(key)
        if isinstance(rows, Sized):
            return len(rows)
    return 1
