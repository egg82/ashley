"""Several tool sources as one `Tools`: the catalogues merged, each call routed to the source that offered it. Keys
name the sources (`house`, `search`; inside the look-up, `web`, `places`), and the mapping's order is the order their
tools and instructions are offered in. Each source caches its own catalogue as it sees fit; this keeps only which source offered which name."""

import asyncio
import logging
import time
from collections.abc import Mapping, Sequence

from .. import logs
from ..inference.model import Tier, ToolCall, ToolResult, ToolSpec
from .action_judge import Vetting
from .tools import Catalogue, Tools, ToolsUnavailable

log = logging.getLogger("ashley.tools")


class CompositeTools(Tools):
    def __init__(self, sources: Mapping[str, Tools]) -> None:
        self._sources = dict(sources)
        self._routes: dict[str, Tools] = {}   # tool name -> the source that offered it in the latest catalogue

    async def catalogue(self) -> Catalogue:
        """Every source asked at once. One that raises ToolsUnavailable is named in `unreachable`, after which come the
        keys a source that answered named in its own (a Composite inside this one); `now` is the sources' own, joined in
        source order like the instructions; raises
        ToolsUnavailable only when every source did. A name an earlier source offered is dropped from a later one,
        logged `tools.duplicate`."""
        keys = list(self._sources)
        got = await asyncio.gather(*(self._sources[k].catalogue() for k in keys), return_exceptions=True)
        reached: list[tuple[str, Catalogue]] = []
        unreachable: list[str] = []
        for key, result in zip(keys, got, strict=True):
            if isinstance(result, ToolsUnavailable):
                unreachable.append(key)
            elif isinstance(result, BaseException):
                raise result
            else:
                reached.append((key, result))
        if not reached:
            raise ToolsUnavailable("no tool source answered")
        return self._merge(reached, tuple(unreachable))

    def _merge(self, reached: list[tuple[str, Catalogue]], unreachable: tuple[str, ...]) -> Catalogue:
        specs: list[ToolSpec] = []
        owner: dict[str, str] = {}
        routes: dict[str, Tools] = {}
        for key, catalogue in reached:
            for spec in catalogue.specs:
                if spec.name in owner:
                    logs.warning(log, "tools.duplicate", tool=spec.name, kept=owner[spec.name], dropped=key)
                    continue
                owner[spec.name] = key
                routes[spec.name] = self._sources[key]
                specs.append(spec)
        self._routes = routes
        texts = [c.instructions.strip() for _, c in reached if c.instructions and c.instructions.strip()]
        inner = tuple(key for _, c in reached for key in c.unreachable)
        now = [c.now.strip() for _, c in reached if c.now and c.now.strip()]
        sources = tuple(key for key, c in reached if c.specs)
        return Catalogue(tuple(specs), "\n\n".join(texts) or None, unreachable + inner, "\n\n".join(now) or None,
                         sources, owner)

    async def call(self, call: ToolCall) -> ToolResult:
        started = time.monotonic()
        if call.name not in self._routes:
            try:
                await self.catalogue()
            except ToolsUnavailable:
                pass
        source = self._routes.get(call.name)
        if source is None:
            logs.info(log, "tools.call", tool=call.name, outcome="unknown_tool",
                      duration_ms=int((time.monotonic() - started) * 1000))
            return ToolResult(call.id, f"no tool named {call.name}", is_error=True)
        return await source.call(call)

    async def for_turn(self) -> Tools:
        """A Composite over each source's own `for_turn`; this one when none changed."""
        keys = list(self._sources)
        turn = await asyncio.gather(*(self._sources[k].for_turn() for k in keys))
        if all(t is self._sources[k] for k, t in zip(keys, turn, strict=True)):
            return self
        return CompositeTools(dict(zip(keys, turn, strict=True)))

    async def tier(self, call: ToolCall) -> Tier | None:
        """The tier the source that offered the tool gives; the argument rules' for a name no source offers."""
        source = self._routes.get(call.name)
        return await super().tier(call) if source is None else await source.tier(call)

    async def vetted(self, call: ToolCall, words: Sequence[str]) -> Vetting | None:
        """What the source that offered the tool makes of the call; None for a name no source offers."""
        source = self._routes.get(call.name)
        return None if source is None else await source.vetted(call, words)
