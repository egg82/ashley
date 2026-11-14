"""The Tools service (`ashley.services`): the tools she may offer the model now, and running one it asked for. Callers
import only this module; implementations live beside it. The one wired is a Composite (`composite.CompositeTools`)
over a look-up (`look_up.LookUpTools`), a sub-agent that alone reads web search through SearXNG
(`web_search.WebSearchTools`). A household with a house gets its own Composite instead (`everyday.Everyday`), which
adds Home Assistant's MCP server (`home_assistant.HomeAssistantTools`), serving HA's Assist tools for the entities
and scripts exposed to Assist, so what she may touch in the house is curated in HA, and places near the house through
Photon (`places.PlacesTools`) in the look-up.

Tool arguments and results can carry people's data and are never logged; tool names, counts, outcomes and durations
are."""

from abc import abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from ..inference.model import Tier, ToolCall, ToolResult, ToolSpec
from ..services import Service
from . import tiers
from .action_judge import Vetting


class ToolsUnavailable(Exception):
    """The tools' source could not be reached or answered with something unusable. Transient: the caller may go on
    without tools, and say so."""


class Unshown(Exception):
    """A change cannot be shown to the person as it would be made, so it is not held; the message is what she is told,
    and names no value."""


@dataclass(frozen=True)
class Catalogue:
    """The tools on offer, names unique, and the source's own guidance for using them (HA's Assist prompt, with its
    overview of the house), to put in the system prompt; None when the source gives none. `unreachable` is the keys of
    the sources that did not answer, in source order (`composite.CompositeTools`). `now` is the source's state at this
    moment (a bench's pieces), for the `moment` layer of the system prompt, never `stable`; None when it has none. `sources` is the keys of the
    sources that answered with a tool, in source order (`composite.CompositeTools`), empty for one that is not a
    Composite. `owners` is the key of the source that offered each tool, by tool name, for a Composite's; empty
    otherwise and for a tool a wrapper added."""

    specs: tuple[ToolSpec, ...]
    instructions: str | None
    unreachable: tuple[str, ...] = ()
    now: str | None = None
    sources: tuple[str, ...] = ()
    owners: Mapping[str, str] = field(default_factory=dict[str, str])


class Tools(Service):
    @classmethod
    def null(cls) -> "Tools":
        return NullTools()

    @abstractmethod
    async def catalogue(self) -> Catalogue:
        """What is on offer now. Raises ToolsUnavailable. Logs `tools.catalogue` with the tool count and duration_ms,
        or `tools.unavailable` with the reason."""

    @abstractmethod
    async def call(self, call: ToolCall) -> ToolResult:
        """Run one call and return its result for `call.id`. Never raises for anything the tool or its source did: a
        name not in the catalogue, a source unreachable or timing out, or the tool reporting failure each return
        `is_error` with a short reason that carries no argument values. Logs `tools.call` with the name, outcome
        (`ok`, `error`, `unknown_tool`, `unavailable`) and duration_ms."""


    async def tier(self, call: ToolCall) -> Tier | None:
        """What a tainted turn does with `call`, when this source knows more than the spec's own `tier`: an argument rule
        of `tiers.json` (`tiers.by_arguments`), which a source that resolves what a call names overrides. None when the
        spec's `tier` stands. Reads nothing that can fail; a wrapper answers as the source that owns the call does."""
        return tiers.by_arguments(call)

    async def vetted(self, call: ToolCall, words: Sequence[str]) -> Vetting | None:
        """What this source makes of a `judged` call before the action judge is asked, given the person's own `words`: a
        view built from the things the call resolves to, or a reason to ask without a judge (`action_judge.Vetting`).
        None when the generic view of the call stands. A wrapper answers as the source that owns the call does."""
        return None

    async def shown(self, call: ToolCall) -> str | None:
        """The line the person is shown for `call` when it is held for their OK, when this source can say exactly what
        it would change; None when the generic summary of its arguments stands. The line is code-written and holds no
        text from outside the household, since it is carried into her later turns. Raises Unshown when the change
        cannot be shown as it would be made. A wrapper answers as the source that owns the call does."""
        return None

    async def for_turn(self) -> "Tools":
        """These tools for one turn. A source that behaves by settings a person may change reads them here, once, and
        answers the whole turn from that read; the rest answer as they are."""
        return self


class NullTools(Tools):
    """Offers nothing: what an unwired process sees. `catalogue` raises ToolsUnavailable, so she says she cannot reach
    the house rather than silently lacking it; `call` answers every call with an error."""

    async def catalogue(self) -> Catalogue:
        raise ToolsUnavailable("Tools is not wired")

    async def call(self, call: ToolCall) -> ToolResult:
        return ToolResult(call.id, "no tools are wired", is_error=True)
