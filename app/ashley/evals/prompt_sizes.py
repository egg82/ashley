"""What each part of her prompt costs in tokens, for one conversation kind and channel (`python -m ashley.evals
prompt-sizes`). `measure` takes the system prompt and tools a real turn built (`channels.turn_prompt.build`, the tools
as `tool_loop.answer` offers them) and counts, with the `Count` it is given (Anthropic's `messages.count_tokens` on the
route's model), each stable-prompt section, the moment layer, each tool and each source's tools, and the reply schema,
every part as the provider sends it (`anthropic_wire`).

A count of one part alone carries the request's fixed cost, so each is a difference: against a one-word request, and a
tool or section against a request holding one minimal tool or a one-character system prompt (`fixed`). The parts are
counted apart, so their tokens need not add up to `whole`, the whole request counted at once. Only names, characters
and tokens are kept, never the text counted."""

import asyncio
import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass

from anthropic.types import MessageParam, TextBlockParam, ToolParam

from ..inference import anthropic_wire
from ..inference.model import SystemPrompt, ToolSpec

PARALLEL = 4
UNOWNED = "(none)"
"""The group of a tool no source offered by name: one a wrapper adds to the turn."""


@dataclass(frozen=True)
class Request:
    """The parts of a `count_tokens` call; every request has `messages`."""

    messages: list[MessageParam]
    system: list[TextBlockParam] | None = None
    tools: list[ToolParam] | None = None
    reply_schema: Mapping[str, object] | None = None


Count = Callable[[str, Request], Awaitable[int]]
"""Input tokens of a request on a model."""


@dataclass(frozen=True)
class Part:
    """`name` (a section id, a tool name or a source key), the characters counted (a tool's are those of its
    definition as sent as JSON), its tokens, and for a source its `members`, how many tools it offers."""

    name: str
    chars: int
    tokens: int
    members: int = 0


@dataclass(frozen=True)
class Sizes:
    """`baseline` is a one-word request, `stable_fixed` and `tools_fixed` what a one-character system prompt and a
    minimal tool add to it. `stable` are the sections in order and `joins` the characters the blank lines between them
    make; `tools` each tool, `groups` each source's tools together, `tools_whole` all of them. `calls` is how many
    counts it took."""

    model: str
    baseline: int
    stable_fixed: int
    tools_fixed: int
    stable: tuple[Part, ...]
    joins: int
    stable_whole: Part
    moment: Part
    tools: tuple[Part, ...]
    groups: tuple[Part, ...]
    tools_whole: Part
    reply_schema: Part
    whole: int
    calls: int


_ONE = [MessageParam(role="user", content=".")]
_STUB = ToolSpec("x", "x", {"type": "object"}, reads=True, outside=False)  # counted, never offered or called


def _tools(specs: Sequence[ToolSpec]) -> Request:
    return Request(list(_ONE), tools=anthropic_wire.tools(tuple(specs)))


def _system(text: str) -> Request:
    return Request(list(_ONE), system=anthropic_wire.system(SystemPrompt(text)))


def _size(value: object) -> int:
    return len(json.dumps(value, sort_keys=True))


async def measure(count: Count, model: str, parts: Sequence[tuple[str, str]], system: SystemPrompt,
                  specs: tuple[ToolSpec, ...], owners: Mapping[str, str], reply_schema: Mapping[str, object]) -> Sizes:
    """Every part of the request `system`, `specs` and `reply_schema` make, counted on `model`: `parts` are the
    sections `system.stable` is joined from (`persona.stable_parts`), `owners` the source of each tool
    (`Catalogue.owners`). Raises ValueError when `parts` do not join to `system.stable`."""
    if "\n\n".join(text for _, text in parts) != system.stable:
        raise ValueError("the stable sections do not make the stable prompt")
    gate = asyncio.Semaphore(PARALLEL)
    calls = 0

    async def n(request: Request) -> int:
        nonlocal calls
        async with gate:
            calls += 1
            return await count(model, request)

    whole_request = Request(anthropic_wire.with_moment(list(_ONE), system.moment), anthropic_wire.system(system),
                            anthropic_wire.tools(specs) if specs else None, reply_schema)
    groups = {key: [s for s in specs if owners.get(s.name, UNOWNED) == key]
              for key in dict.fromkeys(owners.get(s.name, UNOWNED) for s in specs)}
    fixed = [Request(list(_ONE)), _system("."), _tools([_STUB]), _system(system.stable),
             Request(anthropic_wire.with_moment(list(_ONE), system.moment)),
             Request(list(_ONE), reply_schema=reply_schema), whole_request]
    requests = [*fixed, *(_system(text) for _, text in parts), *(_tools([s]) for s in specs),
                *(_tools(g) for g in groups.values()), *([_tools(specs)] if specs else [])]
    counted = list(await asyncio.gather(*(n(r) for r in requests)))
    base, sys_one, tool_one, stable, moment, schema, whole = counted[:7]
    after = iter(counted[7:])
    sections, singles = [next(after) for _ in parts], [next(after) for _ in specs]
    grouped = [next(after) for _ in groups]
    tools = next(after) if specs else tool_one
    stable_fixed, tools_fixed = sys_one - base, tool_one - base
    return Sizes(
        model, base, stable_fixed, tools_fixed,
        tuple(Part(name, len(text), t - base - stable_fixed) for (name, text), t in zip(parts, sections, strict=True)),
        2 * (len(parts) - 1), Part("stable", len(system.stable), stable - base - stable_fixed),
        Part("moment", len(system.moment), moment - base),
        tuple(Part(s.name, _size(anthropic_wire.tools((s,))[0]), t - base - tools_fixed)
              for s, t in zip(specs, singles, strict=True)),
        tuple(Part(key, _size(anthropic_wire.tools(tuple(g))), t - base - tools_fixed, len(g))
              for (key, g), t in zip(groups.items(), grouped, strict=True)),
        Part("tools", _size(anthropic_wire.tools(specs)), tools - base - tools_fixed),
        Part("reply_schema", _size(reply_schema), schema - base), whole, calls)

