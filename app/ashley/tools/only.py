"""A `Tools` with only some of another's tools: the ones named are listed and callable, matched as `Excluding` matches
(an entry, or the entry after a Home Assistant `domain__` prefix), and nothing else is. Names the source does not offer
(a typo in a wake rule, or a source out of reach) are logged `tools.only_unmatched` with their count and how many
sources did not answer, never the names."""

import logging
from collections.abc import Sequence
from dataclasses import replace

from .. import logs
from ..inference.model import Tier, ToolCall, ToolResult
from .action_judge import Vetting
from .excluding import is_excluded
from .tools import Catalogue, Tools

log = logging.getLogger("ashley.tools")


class Only(Tools):
    def __init__(self, source: Tools, allowed: tuple[str, ...]) -> None:
        self._source = source
        self._allowed = allowed

    async def catalogue(self) -> Catalogue:
        """The source's, with only the allowed tools. Raises ToolsUnavailable as the source does."""
        got = await self._source.catalogue()
        unmatched = [a for a in self._allowed if not any(is_excluded(s.name, (a,)) for s in got.specs)]
        if unmatched:
            logs.warning(log, "tools.only_unmatched", count=len(unmatched), unreachable=len(got.unreachable))
        return replace(got, specs=tuple(s for s in got.specs if is_excluded(s.name, self._allowed)))

    async def call(self, call: ToolCall) -> ToolResult:
        """The source's answer; a name not allowed is `unknown_tool`, as if the source never offered it."""
        if not is_excluded(call.name, self._allowed):
            logs.info(log, "tools.call", tool=call.name, outcome="unknown_tool", duration_ms=0)
            return ToolResult(call.id, f"no tool named {call.name}", True)
        return await self._source.call(call)

    async def tier(self, call: ToolCall) -> Tier | None:
        return await self._source.tier(call)

    async def vetted(self, call: ToolCall, words: Sequence[str]) -> Vetting | None:
        return await self._source.vetted(call, words)

    async def shown(self, call: ToolCall) -> str | None:
        return await self._source.shown(call)
