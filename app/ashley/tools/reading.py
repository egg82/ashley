"""A `Tools` with only the tools of another that change nothing (`ToolSpec.reads`): the rest are neither listed nor
callable, so an unattended turn can look things up and never act."""

import logging
from collections.abc import Sequence
from dataclasses import replace

from .. import logs
from ..inference.model import Tier, ToolCall, ToolResult
from .action_judge import Vetting
from .tools import Catalogue, Tools, ToolsUnavailable

log = logging.getLogger("ashley.tools")


class Reading(Tools):
    def __init__(self, source: Tools) -> None:
        self._source = source
        self._reads: frozenset[str] | None = None

    async def catalogue(self) -> Catalogue:
        """The source's, with only its reads. Raises ToolsUnavailable as the source does."""
        got = await self._source.catalogue()
        specs = tuple(s for s in got.specs if s.reads)
        self._reads = frozenset(s.name for s in specs)
        return replace(got, specs=specs)

    async def call(self, call: ToolCall) -> ToolResult:
        """The source's answer for a tool listed as a read; any other name, or any when the source cannot be listed,
        is `unknown_tool`, as if never offered."""
        try:
            reads = self._reads if self._reads is not None else {s.name for s in (await self.catalogue()).specs}
        except ToolsUnavailable:
            reads = frozenset[str]()
        if call.name not in reads:
            logs.info(log, "tools.call", tool=call.name, outcome="unknown_tool", duration_ms=0)
            return ToolResult(call.id, f"no tool named {call.name}", True)
        return await self._source.call(call)

    async def tier(self, call: ToolCall) -> Tier | None:
        return await self._source.tier(call)

    async def vetted(self, call: ToolCall, words: Sequence[str]) -> Vetting | None:
        return await self._source.vetted(call, words)
