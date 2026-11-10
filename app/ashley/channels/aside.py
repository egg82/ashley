"""Her aside: on a turn that can hold, every tool she may call takes one more required argument, `aside`, a short line
to the person in her own words about what she is doing. It is a field of her structured output, so any provider that
calls tools carries it. `ashley.channels.tool_loop` sends her latest round's first aside of a call that did not fail as
her holding line once the turn has run past its kind's `hold_after_s` with no answer; the tool itself never sees the
argument."""

from collections.abc import Iterable, Mapping
from dataclasses import replace

from ..inference.model import Entry, ToolCall, ToolCalls, ToolResult, ToolResults, ToolSpec
from ..inference.reply import Reply
from ..tools.tools import Catalogue, Tools

FIELD = "aside"
DESCRIPTION = ("One whole sentence to the person, in your own voice, about the work itself: what you are making, "
               "changing or finding out for them, and roughly how long it will take when you know. Never which thing "
               "you are reading, opening or checking. When you make several calls at once, write each aside as if it "
               "were the only one. Said to them verbatim only if this takes a while; the answer itself is not here.")


def offered(tools: tuple[ToolSpec, ...]) -> tuple[ToolSpec, ...]:
    """Each of `tools` with `aside` added to its parameters as a required string, except one whose parameters already
    name an `aside`, which is left as it is."""
    return tuple(t if _named(t) else replace(t, parameters=_with_aside(t.parameters)) for t in tools)


def latest(entries: Iterable[Entry]) -> str | None:
    """The first non-blank aside, stripped, of the latest round of tool calls in `entries` that has one; None when no
    round does. Calls made together carry asides written as a sequence, so a later one is a continuation. A call whose
    result came back an error (`ToolResult.is_error`: refused or failed) has no aside, since it describes what did not
    happen."""
    found: str | None = None
    listed = tuple(entries)
    for at, entry in enumerate(listed):
        if isinstance(entry, ToolCalls):
            after = listed[at + 1] if at + 1 < len(listed) else None
            failed = {r.call_id for r in after.results if r.is_error} if isinstance(after, ToolResults) else set[str]()
            said = next((s.strip() for c in entry.calls
                         if c.id not in failed and isinstance(s := c.arguments.get(FIELD), str) and s.strip()), None)
            found = said if said is not None else found
    return found


def holding(line: str) -> Reply:
    """`line` as her holding reply, the same words for a voice and a chat."""
    return Reply(answers=False, spoken=line, text=line)


class Stripped(Tools):
    """`source` with the aside taken out of each call to a tool `offered` added it to."""

    def __init__(self, source: Tools, tools: tuple[ToolSpec, ...]) -> None:
        self._source = source
        self._added = {t.name for t in tools if not _named(t)}

    def offering(self, tools: tuple[ToolSpec, ...]) -> "Stripped":
        """The same source, for the aside added to each of `tools`."""
        return Stripped(self._source, tools)

    async def catalogue(self) -> Catalogue:
        return await self._source.catalogue()

    async def call(self, call: ToolCall) -> ToolResult:
        if call.name in self._added and FIELD in call.arguments:
            call = replace(call, arguments={k: v for k, v in call.arguments.items() if k != FIELD})
        return await self._source.call(call)


def _named(tool: ToolSpec) -> bool:
    properties = tool.parameters.get("properties")
    return isinstance(properties, Mapping) and FIELD in properties


def _with_aside(parameters: Mapping[str, object]) -> dict[str, object]:
    properties = parameters.get("properties")
    required = parameters.get("required")
    return {**parameters,
            "properties": {**(properties if isinstance(properties, Mapping) else {}),
                           FIELD: {"type": "string", "description": DESCRIPTION}},
            "required": [*(required if isinstance(required, list) else []), FIELD]}
