"""The household's filament stock, read through the Stock service (`ashley.stock.stock`), as her `stock_spools` tool.
Offered beside the printing tools, to a known speaker in any chat. It only reads. A spool's brand, colour name and
location are written by whoever added it, or come from a filament catalogue it was added from, so the result is
`outside`. A household with no stock is offered none. Tool arguments and results are never logged."""

import time
from collections.abc import Sized

from .. import services
from ..inference.model import ToolCall, ToolResult, ToolSpec
from ..stock.model import NotConnected, Reason, StockFailed, StockUnavailable
from ..stock.stock import Stock
from . import bench_results, printing_render
from .printing_config import PrintingConfig
from .tools import Catalogue, Tools, ToolsUnavailable

SPOOLS = "stock_spools"
INSTRUCTIONS = ("stock_spools lists the filament spools the household has in stock, most left first: material, brand, "
                "colour, grams left and where it is kept. A spool_id from printing_ams names one of them.")
_FAILED: dict[Reason, tuple[str, str]] = {
    "refused": ("refused", "the filament stock turned the household's key away, or the key may not read it; someone in "
                           "the household can replace it in settings"),
    "unreachable": ("unreachable", "the filament stock did not answer"),
    "unrecognised": ("unrecognised", "the filament stock answered with something unexpected")}


class StockTools(Tools):
    def __init__(self, household_id: int, config: PrintingConfig) -> None:
        self._household_id = household_id
        self._config = config
        self._connected: bool | None = None

    async def catalogue(self) -> Catalogue:
        """No tools when the household has no stock. Raises ToolsUnavailable when its link cannot be read."""
        if not await self._is_connected():
            return Catalogue((), None)
        spec = ToolSpec(SPOOLS, "The spools in the household's filament stock, most left first, with material, brand, "
                        "colour, grams left and location; how many there are, and whether the list was cut.",
                        {"type": "object", "properties": {}}, reads=True, outside=True)
        return Catalogue((spec,), INSTRUCTIONS)

    async def call(self, call: ToolCall) -> ToolResult:
        """Never raises: an unknown tool, no stock, or the stock failing are each an error result."""
        started = time.monotonic()
        if call.name != SPOOLS:
            return bench_results.failed(call, started, "unknown_tool", f"no tool named {call.name}")
        try:
            if not await self._is_connected():
                return bench_results.failed(call, started, "not_connected", "the household has no filament stock")
            got = printing_render.spools(await services.get(Stock).spools(self._household_id, self._config.spools_max))
        except (ToolsUnavailable, StockUnavailable):
            return bench_results.failed(call, started, "unavailable", "the household's connections cannot be read")
        except NotConnected:
            return bench_results.failed(call, started, "not_connected", "the household has no filament stock")
        except StockFailed as e:
            outcome, hint = _FAILED[e.reason]
            return bench_results.failed(call, started, outcome, hint)
        rows = got["spools"]
        return bench_results.ok(call, started, got, rows=len(rows) if isinstance(rows, Sized) else 0)

    async def _is_connected(self) -> bool:
        if self._connected is None:
            try:
                self._connected = await services.get(Stock).connected(self._household_id)
            except StockUnavailable as e:
                raise ToolsUnavailable("stock unavailable") from e
        return self._connected
