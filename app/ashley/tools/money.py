"""The household's finances, read through the Ledger (`ashley.ledger.ledger`), and a transaction's category and note set
through it, as her money tools (`money_specs`). Offered per turn by `ashley.channels.turn_tools.for_turn` only where the
reply reaches the speaker alone (`ashley.channels.audience.owner_alone`), so a change is made only for a named person of
the household; `money_categorise` and `money_note` are not reads, so a reads-only turn is not offered them, and their
tier is `asks`: every call is held for the person's OK (`ashley.tools.outside`), shown by `shown`, and reaches Sure only
when they agree. A household with no ledger is offered none. Tool arguments and results are never logged; `tools.call`
carries the tool, outcome and row count (for a change, how many were set)."""

import asyncio
import time
from collections.abc import Sized

from .. import services
from ..inference.model import ToolCall, ToolResult
from ..ledger.ledger import Ledger
from ..ledger.model import LedgerFailed, LedgerUnavailable, NotConnected, Reason, UnknownCategory
from . import bench_results, money_render
from .money_config import MoneyConfig
from .money_specs import (ACCOUNTS, CATEGORIES, CATEGORISE, CHANGES, INSTRUCTIONS, NAMES, NET_WORTH, NOTE, annotation,
                          categorisation, specs, transaction_query)
from .tools import Catalogue, Tools, ToolsUnavailable, Unshown

_FAILED: dict[Reason, tuple[str, str]] = {
    "refused": ("refused", "Sure turned the household's key away; someone in the household can replace it in settings"),
    "unreachable": ("unreachable", "Sure did not answer"),
    "unrecognised": ("not_sure", "Sure answered with something unexpected")}
"""The outcome and the reason a model is told for each way a read fails."""

_UNAVAILABLE = "the household's connections cannot be read"
_REFUSED_CHANGE = ("Sure turned the change away; the household's key may only read, and someone in the household can "
                   "replace it in settings with one that may write")
_UNKNOWN_CATEGORY = "category_id is not one of the household's categories; money_categories lists them"
_UNKNOWN_TRANSACTION = "a transaction_id is not one of the household's transactions; money_transactions lists them"
_UNSHOWN = "Sure could not be read to show the person what would change; nothing was asked or changed"


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
        except UnknownCategory:
            return bench_results.failed(call, started, "bad_arguments", _UNKNOWN_CATEGORY)
        except LedgerFailed as e:
            outcome, hint = _FAILED[e.reason]
            if call.name in CHANGES and e.reason == "refused":
                hint = _REFUSED_CHANGE
            return bench_results.failed(call, started, outcome, hint)
        if isinstance(got, str):
            return bench_results.failed(call, started, "bad_arguments", got)
        return bench_results.ok(call, started, got, rows=_rows(got))

    async def shown(self, call: ToolCall) -> str | None:
        """For `money_categorise` and `money_note`, what it would change as Sure holds it now
        (`money_render.recategorising`, `money_render.noting`); None for any other tool. Raises Unshown for wrong
        arguments, a category or transaction not the household's, or a ledger that cannot be read."""
        if call.name == NOTE:
            return await self._shown_note(call)
        if call.name != CATEGORISE:
            return None
        asked = categorisation(dict(call.arguments), self._config)
        if isinstance(asked, str):
            raise Unshown(asked)
        ledger, household = services.get(Ledger), self._household_id
        try:
            category = await ledger.category(household, asked.category_id)
            entries = await asyncio.gather(*(ledger.entry(household, t) for t in asked.transaction_ids))
        except (LedgerFailed, LedgerUnavailable, NotConnected) as e:
            raise Unshown(_UNSHOWN) from e
        if category is None:
            raise Unshown(_UNKNOWN_CATEGORY)
        found = [e for e in entries if e is not None]
        if len(found) != len(entries):
            raise Unshown(_UNKNOWN_TRANSACTION)
        return money_render.recategorising(category, found)

    async def _shown_note(self, call: ToolCall) -> str:
        asked = annotation(dict(call.arguments), self._config)
        if isinstance(asked, str):
            raise Unshown(asked)
        try:
            entry = await services.get(Ledger).entry(self._household_id, asked.transaction_id)
        except (LedgerFailed, LedgerUnavailable, NotConnected) as e:
            raise Unshown(_UNSHOWN) from e
        if entry is None:
            raise Unshown(_UNKNOWN_TRANSACTION)
        return money_render.noting(entry, asked.note)

    async def _read(self, call: ToolCall) -> dict[str, object] | str:
        ledger, household = services.get(Ledger), self._household_id
        if call.name == ACCOUNTS:
            return money_render.accounts(await ledger.accounts(household, self._config.accounts_max))
        if call.name == CATEGORIES:
            return money_render.categories(await ledger.categories(household, self._config.categories_max))
        if call.name == NET_WORTH:
            return money_render.net_worth(await ledger.net_worth(household))
        if call.name == CATEGORISE:
            asked = categorisation(dict(call.arguments), self._config)
            if isinstance(asked, str):
                return asked
            return money_render.categorised(await ledger.categorise(household, asked.category_id, asked.transaction_ids))
        if call.name == NOTE:
            noted = annotation(dict(call.arguments), self._config)
            if isinstance(noted, str):
                return noted
            outcome = await ledger.note(household, noted.transaction_id, noted.note)
            return money_render.categorised({noted.transaction_id: outcome})
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
    if "set" in got:
        set_ = got["set"]
        return set_ if isinstance(set_, int) else 0
    for key in ("accounts", "transactions", "categories"):
        rows = got.get(key)
        if isinstance(rows, Sized):
            return len(rows)
    return 1
