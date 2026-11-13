"""`send_readers`, one tool that sends one or more readers at once (`reader.read`): each a sub-agent with its own context,
given a brief she writes and the tools she names from her own, which reports back. The readers of one call run
concurrently, so the turn's loop sees one call in one round, and each sees one inbox or one calendar where she sees only
their reports. What crosses back is bounded here: each report is cut to `report_chars` (`tools.cut`, the cut said).

A reader is handed a `Reading`, so it can list and call only tools that change nothing; and its tools are hers as they
were before this one was added, so a reader cannot send readers. The result is `outside` when any report came from a
reader whose reads were (`decisions.md`, "A turn that has read outside words asks before it does anything consequential
the person did not ask for"), so a change she makes after it is an ask; a reader that did not answer brings nothing back.

Logs `tools.call` with the outcome, how many readers were sent and answered, their rounds and calls summed, whether the
result is outside, and the duration; never a brief, a tool a reader was given, or a report."""

import asyncio
import json
import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from importlib import resources
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .. import logs
from ..inference.model import DEFAULT_VARIANT, SystemPrompt, Task, ToolCall, ToolResult, ToolSpec
from . import cut, reader, readers_config
from .readers_config import ReadersConfig
from .reading import Reading
from .tools import Catalogue, Tools, ToolsUnavailable

log = logging.getLogger("ashley.tools")

NAME = "send_readers"
TASK: Task = "look_up"
DESCRIPTION = ("Send readers out to read for you, several at once. Each reader has its own context, reads with only the "
               "tools of yours you name for it (it is given only those that read, so it changes nothing), and returns a "
               "short report. Use it when an answer needs several sources read, or more text than you need to see "
               "yourself: one reader per source, all in one call, since they run at the same time. Write each brief in "
               "full, with any date, person or name it depends on: a reader sees nothing else of the conversation.")
PARAMETERS = {"type": "object", "properties": {
    "readers": {"type": "array", "items": {"type": "object", "properties": {
        "brief": {"type": "string", "description": "What this reader reads and what its report should say."},
        "tools": {"type": "array", "items": {"type": "string"},
                  "description": "The names of your tools this reader may use."}},
        "required": ["brief", "tools"]}},
    "now": {"type": "string", "description": "The household's local date, weekday and time now, as your prompt gives it."}},
    "required": ["readers", "now"]}
SPEC = ToolSpec(NAME, DESCRIPTION, PARAMETERS, reads=True, outside=True)


class ReaderReport(BaseModel):
    """A reader's reply. Every field is required and has no default, so the schema a model is sent states each."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    found: bool = Field(description="True when what you read answers the brief; false when it does not.")
    report: str = Field(description="What the brief asked for, in plain words, names, dates, times and amounts as read. "
                                    "When nothing answers it, what was found instead.")


@dataclass(frozen=True)
class _Brief:
    brief: str
    tools: tuple[str, ...]


@dataclass(frozen=True)
class _Sent:
    """One reader's part of the result, and what its loop took."""

    body: Mapping[str, object]
    took: reader.Took
    answered: bool


class ReaderTools(Tools):
    def __init__(self, subset: Callable[[tuple[str, ...]], Reading], config: ReadersConfig | None = None) -> None:
        """`subset` makes one reader's tools from the names she gave it; it is called once for each reader sent."""
        self._subset = subset
        self._config = config or readers_config.load()
        self._prompt = resources.files("ashley.tools").joinpath("readers.md").read_text(encoding="utf-8").strip()

    async def catalogue(self) -> Catalogue:
        """One tool, `send_readers`."""
        return Catalogue((SPEC,), None)

    async def call(self, call: ToolCall) -> ToolResult:
        """Each reader's report in the order sent, as `{"readers": [...]}`, an entry `{"found", "report"}` or
        `{"error"}`. An unknown name, briefs that are not a list of a brief and its tool names, or more readers than
        `max_readers` are an error and send none."""
        started = time.monotonic()
        if call.name != NAME:
            return self._done(call, "unknown_tool", started, (), ToolResult(call.id, f"no tool named {call.name}", True))
        briefs = _briefs(call.arguments.get("readers"))
        if briefs is None:
            return self._done(call, "error", started, (), ToolResult(
                call.id, "send_readers needs readers, each with a brief and a list of tool names", True))
        if len(briefs) > self._config.max_readers:
            return self._done(call, "error", started, (), ToolResult(
                call.id, f"send at most {self._config.max_readers} readers in one call", True))
        now = call.arguments.get("now")
        sent = tuple(await asyncio.gather(*(self._one(b, now) for b in briefs)))
        outside = any(s.answered and s.took.outside for s in sent)
        body = json.dumps({"readers": [s.body for s in sent]}, ensure_ascii=False)
        return self._done(call, "ok", started, sent, ToolResult(call.id, body, outside=outside))

    async def _one(self, brief: _Brief, now: object) -> _Sent:
        took = reader.Took()
        sources = self._subset(brief.tools)
        try:
            catalogue = await sources.catalogue()
        except ToolsUnavailable:
            return _Sent({"error": "the reader's tools could not be reached"}, took, False)
        if not catalogue.specs:
            return _Sent({"error": "none of the tools named is one of yours that reads"}, took, False)
        try:
            got = await reader.read(TASK, self._system(catalogue.instructions), reader.asked(brief.brief, now), sources,
                                    catalogue.specs, reader.Limits(self._config.max_rounds, self._config.result_chars),
                                    ReaderReport, took)
        except reader.NoAnswer:
            return _Sent({"error": "the reader did not answer"}, took, False)
        shown = cut.visible(got.report, self._config.report_chars)
        return _Sent({"found": got.found, "report": got.report if shown is None else shown.text}, took, True)

    def _system(self, instructions: str | None) -> dict[str, SystemPrompt]:
        """The readers' prompt, then the guidance that comes with the tools, when they bring any."""
        guidance = f"\n\nWhat the tools' own source says about them:\n\n{instructions.strip()}" if instructions else ""
        return {DEFAULT_VARIANT: SystemPrompt(self._prompt + guidance)}

    def _done(self, call: ToolCall, outcome: str, started: float, sent: tuple[_Sent, ...],
              result: ToolResult) -> ToolResult:
        logs.info(log, "tools.call", tool=call.name, outcome=outcome, readers=len(sent),
                  answered=sum(s.answered for s in sent), rounds=sum(s.took.rounds for s in sent),
                  calls=sum(s.took.calls for s in sent), outside=bool(result.outside),
                  duration_ms=int((time.monotonic() - started) * 1000))
        return result


def _briefs(raw: object) -> tuple[_Brief, ...] | None:
    """The readers as sent; None unless a non-empty list of objects, each with a non-empty `brief` and `tools` a list
    of names."""
    loose: Any = raw
    if not isinstance(raw, list) or not raw:
        return None
    found: list[_Brief] = []
    for item in list[object](loose):
        each: Any = item
        if not isinstance(item, dict):
            return None
        fields = dict[object, object](each)
        brief, tools = fields.get("brief"), fields.get("tools")
        names: Any = tools
        if not isinstance(brief, str) or not brief.strip() or not isinstance(tools, list):
            return None
        found.append(_Brief(brief.strip(), tuple(t for t in list[object](names) if isinstance(t, str))))
    return tuple(found)
