"""One round of a turn's tool calls (`tool_loop`): each call run in the order asked, a repeated read not run again,
a change announced to `Steps` before it runs, and the changes of a turn counted."""

import json
import logging
from collections.abc import Mapping
from dataclasses import replace

from .. import logs
from ..inference.model import Entry, ToolCall, ToolCalls, ToolResult, ToolResults
from ..tools.cut import visible
from ..tools.tools import Tools
from . import aside, taint
from .steps import NO_STEPS, Steps

log = logging.getLogger("ashley.tools")


def key(call: ToolCall) -> tuple[str, str]:
    """Her aside is what she says while it runs, not part of the call."""
    arguments = {k: v for k, v in call.arguments.items() if k != aside.FIELD}
    return call.name, json.dumps(arguments, sort_keys=True, default=str)


def changes(call: ToolCall, reading: set[str]) -> bool:
    return call.name not in reading


def changes_in(entries: list[Entry], reading: set[str]) -> int:
    """How many calls in `entries` are changes."""
    return sum(changes(c, reading) for e in entries if isinstance(e, ToolCalls) for c in e.calls)


def reads_made(entries: list[Entry], reading: set[str]) -> dict[tuple[str, str], str]:
    """The call id of the first read of each name and arguments made in `entries` since the last change that ran."""
    made: dict[tuple[str, str], str] = {}
    for entry in entries:
        if isinstance(entry, ToolCalls):
            for call in entry.calls:
                if not changes(call, reading):
                    made.setdefault(key(call), call.id)
                else:
                    made.clear()
    return made


async def run(asked: ToolCalls, max_chars: int, source: Tools, reading: set[str],
              made: dict[tuple[str, str], str], conversation_id: int | None, outside: Mapping[str, bool],
              steps: Steps = NO_STEPS, done: dict[str, ToolResult] | None = None) -> ToolResults:
    """Each call in the order asked, one at a time, each result cut to `max_chars` with the cut said in what she reads (`tools.cut`), except a call already in `done`. A
    read with the name and arguments of one already made, in `made` or earlier in `asked`, is not run: its result says
    she has the earlier call's result (or its error), and the call's id. A change empties `made`, so a read after it
    runs again. A change is never matched against `made`, so a repeated change is run. Each change is announced to
    `steps` before it runs, and each result after. The first result that carries outside words (`taint.taints` by
    `outside`) is recorded with `steps.tainted` before it is returned, logged `outside.tainted`. Mutates `made` and
    `done`."""
    done = {} if done is None else done
    repeated: list[str] = []
    for call in asked.calls:
        if call.id in done:
            continue
        earlier = made.get(key(call))
        if earlier is not None:
            repeated.append(call.name)
            got = ToolResult(call.id, f"Not run again: this is the same call as {earlier} and its result (or "
                                      "error) is already above. Use it, or answer.", is_error=False)
        elif not changes(call, reading):
            made[key(call)] = call.id
            got = await source.call(call)
        else:
            made.clear()
            await steps.starting(call)
            got = await source.call(call)
        if earlier is None and taint.taints(call.name, got, outside) and await steps.tainted(call.name):
            logs.info(log, "outside.tainted", conversation=conversation_id, by=call.name)
        cut = visible(got.content, max_chars)
        if cut is not None:
            logs.info(log, "tools.cut", conversation=conversation_id, tool=call.name, chars=cut.total, shown=cut.shown,
                      limit=max_chars)
            got = replace(got, content=cut.text)
        done[call.id] = got
        await steps.ran(done[call.id])
    if repeated:
        logs.info(log, "tools.repeat", conversation=conversation_id, repeats=len(repeated),
                  tools=",".join(sorted(set(repeated))))
    return ToolResults(tuple(done[c.id] for c in asked.calls))

