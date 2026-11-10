"""Helpers for the blind tool-use contract tests: tool values, valid exchanges, hypothesis strategies over them, and a
scripted fake `Provider` written against the tool-carrying `Provider.complete`."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from ashley.inference.model import (Entry, Message, Prompt, SystemPrompt, ToolCall, ToolCalls, ToolChoice, ToolResult, ToolResults,
                                    ToolSpec, Usage)
from ashley.inference.provider import Completion, Failure, Provider, ProviderFailed, ProviderRefused, ToolUse
from hypothesis import strategies as st
from inference_support import USAGE, Clock
from pydantic import BaseModel

SCHEMA: dict[str, object] = {"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]}
LIGHTS = ToolSpec("lights_on", "Turn lights on", SCHEMA)
WEATHER = ToolSpec("weather", "Look up the weather", {"type": "object", "properties": {}})
TOOLS = (LIGHTS, WEATHER)
SYSTEM: Mapping[str, SystemPrompt] = {"default": SystemPrompt("be Ashley")}


def call(id_: str = "c1", name: str = "lights_on", **arguments: object) -> ToolCall:
    return ToolCall(id_, name, arguments or {"q": "hall"})


def results_for(calls: Iterable[ToolCall], content: str = "done", is_error: bool = False) -> ToolResults:
    return ToolResults(tuple(ToolResult(c.id, content, is_error) for c in calls))


def tool_prompt(*entries: Entry, tools: tuple[ToolSpec, ...] = TOOLS, tool_choice: ToolChoice = "auto",
                system: Mapping[str, SystemPrompt] = SYSTEM) -> Prompt:
    return Prompt(dict(system), entries, tools, tool_choice)


def one_round(calls: tuple[ToolCall, ...] = (call(),), **kw: Any) -> Prompt:
    """A person asks, she asks for `calls`, the results come back: the prompt of the step after the tool round."""
    return tool_prompt(Message("person", "turn it on"), ToolCalls(calls), results_for(calls), **kw)


def asked(*calls: ToolCall, usage: Usage = USAGE) -> ToolUse:
    return ToolUse(ToolCalls(tuple(calls)), usage)


@dataclass(frozen=True)
class Turn:
    """What one scripted call does: answer `data` as the asked-for output, ask for tools, or raise `error`."""

    data: Mapping[str, object] | None = None
    tool_use: ToolUse | None = None
    error: ProviderFailed | ProviderRefused | None = None
    seconds: float = 0.0


def say(text: str = "answer") -> Turn:
    return Turn(data={"spoken": text, "text": text})


def want(*calls: ToolCall, usage: Usage = USAGE, seconds: float = 0.0) -> Turn:
    return Turn(tool_use=asked(*calls, usage=usage), seconds=seconds)


def broke(failure: Failure) -> Turn:
    return Turn(error=ProviderFailed(failure, f"{failure} (status 000)", None))


def declined() -> Turn:
    return Turn(error=ProviderRefused("declined", None))


@dataclass(frozen=True)
class Received:
    """One `Provider.complete` call as received."""

    model: str
    params: Mapping[str, object]
    system: SystemPrompt
    messages: tuple[Entry, ...]
    tools: tuple[ToolSpec, ...]
    tool_choice: ToolChoice
    output: type[BaseModel]
    timeout_s: float


@dataclass
class ScriptedProvider(Provider):
    """Plays its script one turn per call (the last repeats), moving the clock as the turn says."""

    provider_name: str
    script: list[Turn] = field(default_factory=lambda: [say()])
    clock: Clock | None = None
    got: list[Received] = field(default_factory=list[Received])

    @property
    def name(self) -> str:
        return self.provider_name

    def check_params(self, params: Mapping[str, object]) -> None:
        return None

    async def complete[T: BaseModel](self, model: str, params: Mapping[str, object], system: SystemPrompt,
                                      messages: tuple[Entry, ...], tools: tuple[ToolSpec, ...],
                                      tool_choice: ToolChoice, output: type[T],
                                      timeout_s: float) -> Completion[T] | ToolUse:
        self.got.append(Received(model, params, system, messages, tools, tool_choice, output, timeout_s))
        turn = self.script[min(len(self.got), len(self.script)) - 1]
        if self.clock is not None:
            self.clock.advance(turn.seconds)
        if turn.error is not None:
            raise turn.error
        if turn.tool_use is not None:
            return turn.tool_use
        assert turn.data is not None
        return Completion(output.model_validate(turn.data), USAGE)


def provider(name: str, *script: Turn, clock: Clock | None = None) -> ScriptedProvider:
    return ScriptedProvider(name, list(script) or [say()], clock)


# Hypothesis strategies over valid exchanges.

_names = st.text(alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-", min_size=1, max_size=64)
_words = st.text(alphabet=st.characters(categories=("L", "N")), min_size=1, max_size=12)
_args = st.dictionaries(st.text(alphabet="abcdef", min_size=1, max_size=4), st.one_of(_words, st.integers(), st.booleans()),
                        max_size=3)


@st.composite
def tool_specs(draw: st.DrawFn) -> tuple[ToolSpec, ...]:
    names = draw(st.lists(_names, min_size=1, max_size=4, unique=True))
    return tuple(ToolSpec(n, draw(_words), {"type": "object", "properties": {}}) for n in names)


@st.composite
def exchanges(draw: st.DrawFn) -> tuple[tuple[ToolSpec, ...], tuple[Entry, ...]]:
    """Tools and a valid history: several rounds of person text, calls (several per round) and their results, ending on
    a person message or on results."""
    tools = draw(tool_specs())
    entries: list[Entry] = [Message("person", draw(_words))]
    serial = 0
    for _ in range(draw(st.integers(0, 4))):
        calls: list[ToolCall] = []
        for _ in range(draw(st.integers(1, 3))):
            serial += 1
            calls.append(ToolCall(f"id{serial}", draw(st.sampled_from([t.name for t in tools])), draw(_args)))
        entries.append(ToolCalls(tuple(calls)))
        entries.append(ToolResults(tuple(ToolResult(c.id, draw(_words), draw(st.booleans())) for c in calls)))
        if draw(st.booleans()):
            entries.append(Message("ashley", draw(_words)))
            entries.append(Message("person", draw(_words)))
    return tools, tuple(entries)
