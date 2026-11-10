"""The household's finances, read through the Ledger (`ashley.ledger.ledger`), as her money tools (`money_specs`).
Offered per turn by `ashley.channels.turn_tools.for_turn` only where the reply reaches the speaker alone
(`ashley.channels.audience.owner_alone`). A household with no ledger is offered none. Tool arguments and results are
never logged; `tools.call` carries the tool, outcome and row count."""

import time
from collections.abc import Sized

from .. import services
from ..inference.model import ToolCall, ToolResult
from ..ledger.ledger import Ledger
from ..ledger.model import LedgerFailed, LedgerUnavailable, NotConnected, Reason
from . import bench_results, money_render
from .money_config import MoneyConfig
from .money_specs import ACCOUNTS, CATEGORIES, INSTRUCTIONS, NAMES, NET_WORTH, specs, transaction_query
from .tools import Catalogue, Tools, ToolsUnavailable

_FAILED: dict[Reason, tuple[str, str]] = {
    "refused": ("refused", "Sure turned the household's key away; someone in the household can replace it in settings"),
    "unreachable": ("unreachable", "Sure did not answer"),
    "unrecognised": ("not_sure", "Sure answered with something unexpected")}
"""The outcome and the reason a model is told for each way a read fails."""

_UNAVAILABLE = "the household's connections cannot be read"


class MoneyTools(Tools):
    def __init__(self, household_id: int, config: MoneyConfig) -> None:
        self._household_id = household_id
        self._config = config
        self._connected: bool | None = None

    async def catalogue(self) -> Catalogue:
        """No tools when the household has no ledger. Raises ToolsUnavailable when its link cannot be read."""
        return Catalogue(specs(self._config), INSTRUCTIONS) if await self._is_connected() else Catalogue((), None)

    async def call(self, call: ToolCall) -> ToolResult:
        """Never raises: an unknown tool, bad arguments, no ledger, or the ledger failing are each an error result."""
        started = time.monotonic()
        if call.name not in NAMES:
            return bench_results.failed(call, started, "unknown_tool", f"no tool named {call.name}")
        try:
            if not await self._is_connected():
                return bench_results.failed(call, started, "not_connected", "the household has not connected Sure")
            got = await self._read(call)
        except (ToolsUnavailable, LedgerUnavailable):
            return bench_results.failed(call, started, "unavailable", _UNAVAILABLE)
        except NotConnected:
            return bench_results.failed(call, started, "not_connected", "the household has not connected Sure")
        except LedgerFailed as e:
            outcome, hint = _FAILED[e.reason]
            return bench_results.failed(call, started, outcome, hint)
        if isinstance(got, str):
            return bench_results.failed(call, started, "bad_arguments", got)
        return bench_results.ok(call, started, got, rows=_rows(got))

    async def _read(self, call: ToolCall) -> dict[str, object] | str:
        ledger, household = services.get(Ledger), self._household_id
        if call.name == ACCOUNTS:
            return money_render.accounts(await ledger.accounts(household, self._config.accounts_max))
        if call.name == CATEGORIES:
            return money_render.categories(await ledger.categories(household, self._config.categories_max))
        if call.name == NET_WORTH:
            return money_render.net_worth(await ledger.net_worth(household))
        query = transaction_query(dict(call.arguments), self._config)
        if isinstance(query, str):
            return query
        return money_render.transactions(await ledger.transactions(household, query))

    async def _is_connected(self) -> bool:
        if self._connected is None:
            try:
                self._connected = await services.get(Ledger).connected(self._household_id)
            except LedgerUnavailable as e:
                raise ToolsUnavailable("ledger unavailable") from e
        return self._connected


def _rows(got: dict[str, object]) -> int:
    for key in ("accounts", "transactions", "categories"):
        rows = got.get(key)
        if isinstance(rows, Sized):
            return len(rows)
    return 1
