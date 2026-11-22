"""Tools offered on demand. A turn has a core (`core_for`): the sources it is offered from its first step, the rest of
what `turn_tools.for_turn` built for it only after she asks for them by name with `use_tools`, from her next step on.
By default the core is the data in `on_demand.json` by `Inbound.medium`; an eval's cut (`cut.Cut.core`) overrides it.
`Loading` wraps the turn's tools and adds that tool: it can offer only the sources the turn's tools already hold (a
narrowing has cut the rest), and the groups loaded so far are read from the turn's own entries (`loaded`), so a turn
another runner resumes offers what it had. `thinned` makes the offer."""

import json
import logging
from collections.abc import Mapping, Sequence
from dataclasses import replace
from functools import cache
from importlib import resources

from pydantic import BaseModel, TypeAdapter, ValidationError

from .. import logs
from ..inference.model import Entry, Tier, ToolCall, ToolCalls, ToolResult, ToolResults, ToolSpec
from ..tools.action_judge import Vetting
from ..tools.tools import Catalogue, Tools, ToolsUnavailable
from . import cut, tool_groups
from .model import Inbound, Medium

log = logging.getLogger("ashley.tools")

LOADER = "use_tools"
"""The loader tool's name. A catalogue holding it is one whose groups load on demand."""
FIELD = "groups"
_NAMES = TypeAdapter(list[str])
_OBJECT = TypeAdapter(dict[str, object])
_MEDIA: tuple[Medium, ...] = ("text", "spoken")


def parse(data: object) -> dict[Medium, frozenset[str] | None]:
    """The default core per medium from `on_demand.json`'s parsed content: an object with exactly `text` and `spoken`,
    each a list of source keys offered from the first step (empty for none) or null for every source. Raises ValueError
    otherwise."""
    try:
        named = _OBJECT.validate_python(data)
    except ValidationError as e:
        raise ValueError(f"on_demand.json has exactly {', '.join(_MEDIA)}") from e
    if set(named) != set(_MEDIA):
        raise ValueError(f"on_demand.json has exactly {', '.join(_MEDIA)}")
    cores: dict[Medium, frozenset[str] | None] = {}
    for medium in _MEDIA:
        value = named[medium]
        if value is None:
            cores[medium] = None
            continue
        try:
            keys = _NAMES.validate_python(value)
        except ValidationError as e:
            raise ValueError(f"on_demand.json {medium!r} is null or a list of source keys") from e
        if not all(keys):
            raise ValueError(f"on_demand.json {medium!r} is null or a list of source keys")
        cores[medium] = frozenset(keys)
    return cores


@cache
def defaults() -> dict[Medium, frozenset[str] | None]:
    """`parse` of the `on_demand.json` shipped beside this module."""
    return parse(json.loads(resources.files("ashley.channels").joinpath("on_demand.json").read_text()))


def core_for(inbound: Inbound) -> frozenset[str] | None:
    """The sources the turn is offered from its first step, the rest loading on demand; None when it is offered every
    source: an `eligible` turn's installed eval cut (`cut.Cut.core`), else the default for its medium (`defaults`)."""
    if not eligible(inbound):
        return None
    asked = cut.active().core
    if asked is None:
        return defaults()[inbound.medium]
    return None if isinstance(asked, str) else asked


def eligible(inbound: Inbound) -> bool:
    """Whether the turn's tools load on demand: not a turn already narrowed to named tools, not a bench's, and not a
    check of an errand or a standing method, whose tools sit beside the rest, and not a turn that begins with her look
    at a camera (`channels.seen`), which holds a call to a tool the turn must offer."""
    return (inbound.tools_only is None and inbound.seen is None and inbound.errand is None and inbound.method is None
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


def free(asked: ToolCalls, entries: Sequence[Entry], tools: Sequence[ToolSpec]) -> int:
    """1 when `asked` is a round of calls to the loader alone and it is one of the first as many such rounds as the
    turn has groups to load (the loader's enum in `tools`, counted from the turn's own `entries`, so a resumed turn
    counts the same); such a round is not one of the turn's `max_tool_rounds`. Else 0."""
    if not asked.calls or any(c.name != LOADER for c in asked.calls):
        return 0
    made = sum(isinstance(e, ToolCalls) and all(c.name == LOADER for c in e.calls) for e in entries)
    return int(made < sum(len(_groups(s)) for s in tools if s.name == LOADER))


def thinned(catalogue: Catalogue, loaded: frozenset[str] = frozenset()) -> Catalogue:
    """A catalogue that holds the loader and a `core` less the sources outside the core that are not `loaded`, with their
    instructions, the loader and the loaded sources' tools last. Any other catalogue as it is."""
    core = catalogue.core
    if core is None or not any(s.name == LOADER for s in catalogue.specs):
        return catalogue
    owners = catalogue.owners
    cut.met(k for k in core if k in owners.values())
    hidden = set(held_back(catalogue, core)) - loaded
    now = tuple(s for s in catalogue.specs if s.name != LOADER and owners.get(s.name) not in loaded | hidden)
    after = tuple(s for s in catalogue.specs if owners.get(s.name) in loaded)
    loader = tuple(s for s in catalogue.specs if s.name == LOADER)
    guidance = {k: v for k, v in catalogue.guidance.items() if k not in hidden}
    return replace(catalogue, specs=(*now, *loader, *after), sources=tuple(k for k in catalogue.sources if k not in hidden),
                   owners={n: k for n, k in owners.items() if k not in hidden}, guidance=guidance,
                   instructions=("\n\n".join(guidance.values()) or None) if catalogue.guidance else catalogue.instructions)


class _Items(BaseModel):
    enum: list[str]


class _Groups(BaseModel):
    items: _Items


class _Properties(BaseModel):
    groups: _Groups


class _Schema(BaseModel):
    properties: _Properties


def _groups(spec: ToolSpec) -> list[str]:
    """The group keys the loader `spec` offers: the enum of its `groups` argument (see `_spec`)."""
    return _Schema.model_validate(spec.parameters).properties.groups.items.enum


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
        return got if not groups else replace(got, specs=(*got.specs, _spec(groups)), core=self._core)

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
                    "offered from your next step on. A group not offered yet is not out of reach: name it here and "
                    f"use it. The groups:\n{lines}",
                    {"type": "object", "properties": {FIELD: {"type": "array", "minItems": 1,
                                                              "items": {"type": "string", "enum": list(groups)}}},
                     "required": [FIELD]}, reads=True, outside=False)
