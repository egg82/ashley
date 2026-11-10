"""Helpers for the blind `tool_loop` tests: a rig of a hand-moved clock, a scripted model that moves it, and a source
that records the calls that reach it. The rig asserts nothing; the tests read what it recorded."""

import math
from collections.abc import Generator, Mapping
from dataclasses import dataclass, field
from typing import TypeVar

import pytest
from ashley import logs, services
from ashley.channels import tool_loop
from ashley.channels.limits import Limits
from ashley.channels.tool_loop import Answer, Held
from ashley.inference.inference import Inference
from ashley.inference.model import Message, Prompt, SystemPrompt, Task, ToolCall, ToolCalls, ToolResult, ToolResults, ToolSpec
from ashley.inference.reply import Reply
from ashley.tools.tools import Catalogue, Tools
from conversations_support import events
from inference_support import Clock, settle
from turns_support import FakeInference
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)
CID = 77
OBJECT: Mapping[str, object] = {"type": "object", "properties": {}}
READ = ToolSpec("lookup", "reads", OBJECT, reads=True)
READ2 = ToolSpec("weather", "reads", OBJECT, reads=True)
CHANGE = ToolSpec("lights_set", "changes", OBJECT)
CHANGE2 = ToolSpec("timer_start", "changes", OBJECT)
SPECS = (READ, READ2, CHANGE, CHANGE2)
ANSWER = Reply(spoken="All done.", text="All done.")
LOOK = Reply(answers=False, spoken="Let me check.", text="Let me check.")


def limits(hold: float | None = None, deadline: float | None = None, rounds: int = 8) -> Limits:
    return Limits(rounds, 8000, 1, 0, math.inf if hold is None else hold, math.inf if deadline is None else deadline)


def call(name: str, id_: str, **arguments: object) -> ToolCall:
    return ToolCall(id_, name, arguments)


def calls(*each: ToolCall) -> ToolCalls:
    return ToolCalls(tuple(each))


class Ticking(FakeInference):
    """Answers each `step` with the next scripted outcome (a `Reply` or `ToolCalls`; `then` once the script is
    spent), then moves `clock` by the next of `seconds` (0 when spent). Under tool choice `none` the answer is
    `ANSWER` whatever was scripted, as a provider's is."""

    def __init__(self, clock: Clock) -> None:
        super().__init__()
        self.clock = clock
        self.seconds: list[float] = []
        self.prompts: list[Prompt] = []

    async def step(self, task: Task, prompt: Prompt, output: type[T], *,
                   conversation_id: int | None = None) -> T | ToolCalls:
        self.prompts.append(prompt)
        outcome = self.script.pop(0) if self.script else self.then
        if isinstance(outcome, Exception):
            raise outcome
        self.clock.advance(self.seconds.pop(0) if self.seconds else 0.0)
        if isinstance(outcome, ToolCalls) and prompt.tool_choice != "none":
            return outcome
        reply = outcome if isinstance(outcome, Reply) else ANSWER
        return output.model_validate(reply.model_dump())

    @property
    def choices(self) -> list[str]:
        return [p.tool_choice for p in self.prompts]


class Source(Tools):
    """Records every call that reaches it; a name returns its `results` entry or an ok result carrying the call id."""

    def __init__(self) -> None:
        self.called: list[ToolCall] = []
        self.results: dict[str, ToolResult] = {}

    async def catalogue(self) -> Catalogue:
        return Catalogue(SPECS, "")

    async def call(self, call: ToolCall) -> ToolResult:
        self.called.append(call)
        if call.name in self.results:
            found = self.results[call.name]
            return ToolResult(call.id, found.content, found.is_error)
        return ToolResult(call.id, f'{{"ok": true, "ran": "{call.id}"}}')

    def names(self) -> list[str]:
        return [c.name for c in self.called]

    def ids(self) -> list[str]:
        return [c.id for c in self.called]


@dataclass
class Rig:
    clock: Clock
    inference: Ticking
    source: Source
    out: pytest.CaptureFixture[str]
    started: float = field(default=0.0)

    def answer(self, *script: Reply | ToolCalls, lim: Limits | None = None, hold: bool = False,
               tools: tuple[ToolSpec, ...] = SPECS, started: float | None = None) -> Answer | Held:
        self.inference.script = list(script)
        return settle(tool_loop.answer("chat", {"default": SystemPrompt("you are her")}, _HISTORY, tools, lim or limits(),
                                       CID, hold, self.source, started, self.clock))

    def resume(self, held: Held, *script: Reply | ToolCalls, lim: Limits | None = None,
               tools: tuple[ToolSpec, ...] = SPECS, started: float | None = None) -> Answer:
        self.inference.script = list(script)
        return settle(tool_loop.resume(held, "chat", {"default": SystemPrompt("you are her")}, tools, lim or limits(), CID,
                                       self.source, started, self.clock))

    def events(self, event: str) -> list[dict[str, str]]:
        return events(self.out.readouterr().out, event)

    def results_after(self, round_: int) -> tuple[ToolResult, ...]:
        """The results the model was sent for its `round_`th ToolCalls (from 0), read off the next prompt."""
        seen = [e for e in self.inference.prompts[round_ + 1].messages if isinstance(e, ToolResults)]
        return seen[round_].results


_HISTORY: tuple[Message, ...] = (Message("person", "do the thing"),)


@pytest.fixture
def rig(capsys: pytest.CaptureFixture[str]) -> Generator[Rig]:
    clock = Clock(1000.0)
    inference = Ticking(clock)
    services.register(Inference, inference)
    logs.setup()
    capsys.readouterr()
    yield Rig(clock, inference, Source(), capsys, 1000.0)
    services.unregister(Inference)


def as_answer(out: Answer | Held) -> Answer:
    assert isinstance(out, Answer), f"held: {out}"
    return out


def as_held(out: Answer | Held) -> Held:
    assert isinstance(out, Held), f"answered: {out}"
    return out
