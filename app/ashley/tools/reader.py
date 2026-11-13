"""A reader: a sub-agent with its own context, which steps its own `Inference.step` loop over the tools it is given until
it replies in the shape asked for. `look_up` runs one per question. It sees only its first message and what its own
calls return, never the conversation that sent it; what crosses back is its caller's to bound."""

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import TypeVar

from pydantic import BaseModel

from .. import services
from ..inference.inference import Inference, InferenceRefused, InferenceUnavailable
from ..inference.model import (Entry, Message, Prompt, SystemPrompt, Task, ToolCalls, ToolChoice, ToolResults,
                               ToolSpec)
from . import cut
from .tools import Tools

T = TypeVar("T", bound=BaseModel)


class NoAnswer(Exception):
    """The loop ended without a reply: inference was unavailable or refused, or it asked for tools under `none`."""


@dataclass(frozen=True)
class Limits:
    """How many rounds of tool calls a reader may make before it must reply, and how much of each result it reads."""

    max_rounds: int
    result_chars: int


@dataclass
class Took:
    """What one reader's loop took, for its caller's log line."""

    rounds: int = 0
    calls: int = 0


async def read(task: Task, system: Mapping[str, SystemPrompt], first: str, sources: Tools,
               tools: tuple[ToolSpec, ...], limits: Limits, output: type[T], took: Took) -> T:
    """Steps under tool choice `auto` for up to `max_rounds` rounds of tool calls, then one under `none`. Counts the rounds
    and calls into `took`. Raises NoAnswer."""
    entries: list[Entry] = [Message("person", first)]
    for rounds in range(limits.max_rounds + 1):
        choice: ToolChoice = "auto" if rounds < limits.max_rounds else "none"
        got = await _step(task, Prompt(system, tuple(entries), tools, choice), output)
        if not isinstance(got, ToolCalls):
            return got
        if choice == "none":
            break
        took.rounds, took.calls = rounds + 1, took.calls + len(got.calls)
        entries += [got, await _results(sources, got, limits.result_chars)]
    raise NoAnswer()


def asked(text: str, now: object) -> str:
    """A question or brief as a reader reads it: after the moment it was asked, when she gave one."""
    if isinstance(now, str) and now.strip():
        return f"Now: {now.strip()[:80]}\n\n{text}"
    return text


async def _step(task: Task, prompt: Prompt, output: type[T]) -> T | ToolCalls:
    try:
        return await services.get(Inference).step(task, prompt, output)
    except (InferenceUnavailable, InferenceRefused) as e:
        raise NoAnswer() from e


async def _results(sources: Tools, calls: ToolCalls, result_chars: int) -> ToolResults:
    """Each call in the order asked, one at a time, each result cut to `result_chars`."""
    results = [await sources.call(c) for c in calls.calls]
    return ToolResults(tuple(replace(r, content=_seen(r.content, result_chars)) for r in results))


def _seen(content: str, limit: int) -> str:
    got = cut.visible(content, limit)
    return content if got is None else got.text
