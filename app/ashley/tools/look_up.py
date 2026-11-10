"""`look_up`, a sub-agent she calls as one tool: it alone reads search results, through its own `Inference.step` loop
on the `look_up` task with only the search sources' tools, and hands back a short answer in fixed fields. So text
strangers wrote never enters her context, and nothing that reads it has a tool that acts on the house. Its sources are
made afresh for each call (`pages.Pages` among them), so what one look-up searched and read never reaches another.
What crosses back is bounded here, in code: the answer's length and the number and length of its sources and
references. A reference names a search result by its number (`results.Results`, the turn's store) with its site, never
its URL: it is how she puts a page or video on a bench (`bench_reference`).

The `tools.call` line carries the outcome, the rounds and calls the loop took, whether it found an answer, and the
duration; never the question, the answer, the sources or a query."""

import json
import logging
import time
from collections.abc import Callable
from urllib.parse import urlsplit
from dataclasses import replace
from importlib import resources

from pydantic import BaseModel, ConfigDict, Field

from .. import logs, services
from ..inference.inference import Inference, InferenceRefused, InferenceUnavailable
from ..inference.model import (DEFAULT_VARIANT, Entry, Message, Prompt, SystemPrompt, Task, ToolCall, ToolCalls, ToolChoice,
                               ToolResult, ToolResults, ToolSpec)
from . import cut, results
from .look_up_config import LookUpConfig
from .tools import Catalogue, Tools, ToolsUnavailable

log = logging.getLogger("ashley.tools")

NAME = "look_up"
TASK: Task = "look_up"
DESCRIPTION = ("Look something up on the web, find existing 3D models on Printables, or find places near the house. Returns a short answer and where it came "
               "from. Write the question in full, with any date, place or name it depends on: the look-up sees nothing "
               "else of the conversation. To put a page or video on a bench, ask for it in the question: the answer's `references` "
               "name results by number. To read a page's text on a bench, ask the look-up to read that page too.")
PARAMETERS = {"type": "object", "properties": {
    "question": {"type": "string"},
    "now": {"type": "string", "description": "The household's local date, weekday and time now, as your prompt gives it."}},
    "required": ["question", "now"]}
SPEC = ToolSpec(NAME, DESCRIPTION, PARAMETERS, reads=True, outside=True)
SOURCE_CHARS = 80


def _seen(content: str, limit: int) -> str:
    got = cut.visible(content, limit)
    return content if got is None else got.text


class Reference(BaseModel):
    """A search result the answer points to as the page or video itself: `result` is its number, `what` a few words on it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    result: int = Field(description="The result number search_web gave.")
    what: str = Field(description="A few words on what the page or video is.")


class LookedUp(BaseModel):
    """The sub-agent's reply. Every field is required and has no default, so the schema a model is sent states each."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    found: bool = Field(description="True when the search results answer the question; false when they do not.")
    answer: str = Field(description="The answer in plain words, a sentence or two, numbers and times as the results "
                                    "give them. When nothing answers it, what was found instead.")
    sources: list[str] = Field(description="The sites (hosts) or place names the answer came from.")
    references: list[Reference] = Field(description="When the question asks for a page or video to show, the results "
                                                    "that are themselves one specific such page or video (never a "
                                                    "search page); otherwise empty.")


class _NoAnswer(Exception):
    """The loop ended without a reply: inference was unavailable or refused, or it asked for tools under `none`."""


class LookUpTools(Tools):
    def __init__(self, sources: Callable[[], Tools], config: LookUpConfig) -> None:
        """`sources` makes the search sources for one look-up; it is called once for each `catalogue` and `call`."""
        self._sources = sources
        self._config = config
        self._system = {DEFAULT_VARIANT: SystemPrompt(resources.files("ashley.tools").joinpath("look_up.md")
                                                      .read_text(encoding="utf-8").strip())}

    async def catalogue(self) -> Catalogue:
        """One tool, `look_up`. Raises ToolsUnavailable when the search sources' catalogue does."""
        await self._sources().catalogue()
        return Catalogue((SPEC,), None)

    async def call(self, call: ToolCall) -> ToolResult:
        started = time.monotonic()
        loop = _Loop()
        if call.name != NAME:
            return loop.done(call, "unknown_tool", started, ToolResult(call.id, f"no tool named {call.name}", True))
        question = call.arguments.get("question")
        if not isinstance(question, str) or not question.strip():
            return loop.done(call, "error", started, ToolResult(call.id, "look_up needs a question", True))
        sources = self._sources()
        try:
            catalogue = await sources.catalogue()
            got = await self._run(loop, sources, _asked(question.strip(), call.arguments.get("now")), catalogue.specs)
        except (ToolsUnavailable, _NoAnswer):
            return loop.done(call, "unavailable", started, ToolResult(call.id, "the look-up did not answer", True))
        loop.found = got.found
        return loop.done(call, "ok", started, ToolResult(call.id, self._bounded(got)))

    async def _run(self, loop: "_Loop", sources: Tools, question: str, tools: tuple[ToolSpec, ...]) -> LookedUp:
        """Steps under tool choice `auto` for up to `max_rounds` rounds of tool calls, then one under `none`. Raises
        _NoAnswer."""
        entries: list[Entry] = [Message("person", question)]
        for rounds in range(self._config.max_rounds + 1):
            choice: ToolChoice = "auto" if rounds < self._config.max_rounds else "none"
            got = await self._step(Prompt(self._system, tuple(entries), tools, choice))
            if isinstance(got, LookedUp):
                return got
            if choice == "none":
                break
            loop.rounds, loop.calls = rounds + 1, loop.calls + len(got.calls)
            entries += [got, await self._results(sources, got)]
        raise _NoAnswer()

    async def _step(self, prompt: Prompt) -> LookedUp | ToolCalls:
        try:
            return await services.get(Inference).step(TASK, prompt, LookedUp)
        except (InferenceUnavailable, InferenceRefused) as e:
            raise _NoAnswer() from e

    async def _results(self, sources: Tools, asked: ToolCalls) -> ToolResults:
        """Each call in the order asked, one at a time, each result cut to `result_chars`."""
        results = [await sources.call(c) for c in asked.calls]
        return ToolResults(tuple(replace(r, content=_seen(r.content, self._config.result_chars)) for r in results))

    def _bounded(self, got: LookedUp) -> str:
        sources = [s[:SOURCE_CHARS] for s in got.sources[:self._config.max_sources]]
        body: dict[str, object] = {"found": got.found, "answer": got.answer[:self._config.answer_chars],
                                   "sources": sources}
        named = self._named(got.references)
        if named:
            body["references"] = named
        return json.dumps(body, ensure_ascii=False)

    def _named(self, references: list[Reference]) -> list[dict[str, object]]:
        """The references that name a result of this turn, in order, each with its site; the others are dropped."""
        store = results.current()
        found: list[dict[str, object]] = []
        for ref in references:
            url = store.url(ref.result)
            if url is not None and len(found) < self._config.max_sources:
                found.append({"result": ref.result, "what": ref.what[:SOURCE_CHARS], "site": urlsplit(url).hostname or ""})
        return found


def _asked(question: str, now: object) -> str:
    """The question as the sub-agent reads it: after the moment it was asked, when she gave one."""
    if isinstance(now, str) and now.strip():
        return f"Now: {now.strip()[:80]}\n\n{question}"
    return question


class _Loop:
    """What one call's loop took, for its log line."""

    def __init__(self) -> None:
        self.rounds = 0
        self.calls = 0
        self.found = False

    def done(self, call: ToolCall, outcome: str, started: float, result: ToolResult) -> ToolResult:
        logs.info(log, "tools.call", tool=call.name, outcome=outcome, rounds=self.rounds, calls=self.calls,
                  found=self.found, duration_ms=int((time.monotonic() - started) * 1000))
        return result
