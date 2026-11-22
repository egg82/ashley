"""Tools offered on demand. A turn under a cut with a `core` (`cut.Cut.core`) is offered the sources named there from
its first step, and the rest of what `turn_tools.for_turn` built for it only after she asks for them by name with
`use_tools`, from her next step on. `Loading` wraps the turn's tools and adds that tool: it can offer only the sources
the turn's tools already hold (a narrowing has cut the rest), and the groups loaded so far are read from the turn's own
entries (`loaded`), so a turn another runner resumes offers what it had. `cut.thinned` makes the offer."""

import logging
from collections.abc import Mapping, Sequence
from dataclasses import replace

from pydantic import TypeAdapter, ValidationError

from .. import logs
from ..inference.model import Entry, Tier, ToolCall, ToolCalls, ToolResult, ToolResults, ToolSpec
from ..tools.action_judge import Vetting
from ..tools.tools import Catalogue, Tools, ToolsUnavailable
from . import tool_groups
from .model import Inbound

log = logging.getLogger("ashley.tools")

LOADER = "use_tools"
"""The loader tool's name. A catalogue holding it is one whose groups load on demand."""
FIELD = "groups"
_NAMES = TypeAdapter(list[str])


def eligible(inbound: Inbound) -> bool:
    """Whether the turn's tools load on demand: not a turn already narrowed to named tools, not a bench's, and not a
    check of an errand or a standing method, whose tools sit beside the rest."""
    return (inbound.tools_only is None and inbound.errand is None and inbound.method is None
            and inbound.bench_id is None and inbound.moved_to is None)


def held_back(catalogue: Catalogue, core: frozenset[str]) -> tuple[str, ...]:
    """The keys of the sources that offered a tool in `catalogue`, in order, except `core`."""
    owners = catalogue.owners
    return tuple(dict.fromkeys(k for s in catalogue.specs if (k := owners.get(s.name)) is not None and k not in core))


def loaded(entries: Sequence[Entry]) -> frozenset[str]:
    """The groups the loader's calls in `entries` offered: the arguments of each call whose result is not an error."""
    asked: dict[str, ToolCall] = {}
    groups: set[str] = set()
    for entry in entries:
        if isinstance(entry, ToolCalls):
            asked.update({c.id: c for c in entry.calls if c.name == LOADER})
        elif isinstance(entry, ToolResults):
            groups.update(g for r in entry.results if not r.is_error and r.call_id in asked
                          for g in named(asked[r.call_id].arguments))
    return frozenset(groups)


def named(arguments: Mapping[str, object]) -> list[str]:
    """The group keys a call to the loader names: the strings of its `groups` list, none for any other shape (a list holding anything else is none too)."""
    try:
        return _NAMES.validate_python(arguments.get(FIELD))
    except ValidationError:
        return []


class Loading(Tools):
    """`source` and the loader tool for the groups outside `core` that `source` holds, when it holds any."""

    def __init__(self, source: Tools, core: frozenset[str]) -> None:
        self._source = source
        self._core = core

    async def catalogue(self) -> Catalogue:
        got = await self._source.catalogue()
        groups = held_back(got, self._core)
        return got if not groups else replace(got, specs=(*got.specs, _spec(groups)))

    async def call(self, call: ToolCall) -> ToolResult:
        """The source's answer; `use_tools` is this class's own: it offers groups the turn holds and reaches no source.
        Logs `tools.loaded` with the groups it offered, the tools they hold and the outcome."""
        if call.name != LOADER:
            return await self._source.call(call)
        try:
            got = await self._source.catalogue()
        except ToolsUnavailable:
            return self._answer(call, (), "no tools can be reached right now")
        groups = held_back(got, self._core)
        asked = named(call.arguments)
        if not asked or any(g not in groups for g in asked):
            return self._answer(call, (), f"name groups from the ones this turn has: {', '.join(groups)}")
        counts = {g: sum(got.owners.get(s.name) == g for s in got.specs) for g in dict.fromkeys(asked)}
        return self._answer(call, tuple(counts.items()), None)

    def _answer(self, call: ToolCall, counts: tuple[tuple[str, int], ...], error: str | None) -> ToolResult:
        logs.info(log, "tools.loaded", groups=",".join(g for g, _ in counts), tools=sum(n for _, n in counts),
                  outcome="error" if error else "ok")
        if error:
            return ToolResult(call.id, error, is_error=True)
        return ToolResult(call.id, "Offered from your next step: " + ", ".join(f"{g} ({n} tools)" for g, n in counts))

    async def tier(self, call: ToolCall) -> Tier | None:
        return await self._source.tier(call)

    async def vetted(self, call: ToolCall, words: Sequence[str]) -> Vetting | None:
        return await self._source.vetted(call, words)

    async def shown(self, call: ToolCall) -> str | None:
        return await self._source.shown(call)


def _spec(groups: tuple[str, ...]) -> ToolSpec:
    lines = "\n".join(f"- {g}: {tool_groups.summary(g)}" for g in groups)
    return ToolSpec(LOADER, "Offer more of your tools. You have a few now; name the groups you need and they are "
                    f"offered from your next step on. The groups:\n{lines}",
                    {"type": "object", "properties": {FIELD: {"type": "array", "minItems": 1,
                                                              "items": {"type": "string", "enum": list(groups)}}},
                     "required": [FIELD]}, reads=True, outside=False)
