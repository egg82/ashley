"""Shared setup for the blind "close the gap on the workbench" suite: a scripted model, tools that move a fake clock,
a checkpointed (`Saved`) turn over an in-memory `InFlight`, and a driver that runs a turn through `tool_loop.answer`
and `resume` the way a held turn goes. Written from the spec's contract; nothing here reads her words to decide
anything."""

import json
from collections.abc import Generator, Mapping
from dataclasses import dataclass, replace
from importlib import resources
from typing import Any

import pytest
from ashley import services
from ashley.channels import aside, limits as limits_module
from ashley.channels.checkpoint import Checkpoint, loads
from ashley.channels.inflight import Saved
from ashley.channels.limits import Limits
from ashley.channels.tool_loop import NO_STEPS, Answer, Held, Steps, answer, resume
from ashley.conversations.inflight import Claim, InFlight, NullInFlight
from ashley.conversations.model import Kind
from ashley.inference.inference import Inference
from ashley.inference.model import Message, Prompt, SystemPrompt, Task, ToolCall, ToolCalls, ToolResult, ToolSpec
from ashley.inference.reply import Reply
from ashley.inference.speech import Heard, Speech, SpeechTask, Transcript
from ashley.tools.tools import Catalogue, Tools
from contract.inference_support import Clock
from inflight_blind.ifb_checkpoint_support import checkpoint

START = 1000.0
CONVERSATION = 7
HISTORY = (Message("person", "let's see it"),)
SYSTEM = {"default": SystemPrompt("you are her")}
FINAL = Reply(spoken="Built it.", text="Built it.")
PROMISE = Reply(answers=False, spoken="Give me a moment.", text="Give me a moment.")
STOOD = Reply(spoken="Here is where it stands.", text="Here is where it stands.")

READ = ToolSpec("bench_read", "read the bench", {"type": "object"}, reads=True)
LAST = ToolSpec("bench_last_run", "the last run", {"type": "object"}, reads=True)
RUN = ToolSpec("bench_run", "build the model", {"type": "object"}, reads=False)
EDIT = ToolSpec("bench_edit", "edit a piece", {"type": "object"}, reads=False)
TOOLS = (READ, LAST, RUN, EDIT)

STAND_SPEC_TEXT = ("You can do no more on this now. Tell the person where it stands: what is done, what is not, and "
                   "what they can ask you to do next. Never say you will do more.")


def stand_text() -> str:
    """The `stand` note as shipped in unsaid.json."""
    data = json.loads(resources.files("ashley.channels").joinpath("unsaid.json").read_text())
    return str(data["stand"])


def brainstorm(**changes: Any) -> Limits:
    """The shipped brainstorm limits, with `changes`."""
    return replace(limits_module.load()["brainstorm"], **changes)


def round_of(n: int, *calls: tuple[ToolSpec, str | None]) -> ToolCalls:
    """One round of calls, each a tool and the aside she wrote for it (None: no aside field)."""
    made: list[ToolCall] = []
    for i, (spec, said) in enumerate(calls):
        arguments: dict[str, object] = {"n": n, "i": i}
        if said is not None:
            arguments[aside.FIELD] = said
        made.append(ToolCall(f"r{n}c{i}", spec.name, arguments))
    return ToolCalls(tuple(made))


def one(n: int, spec: ToolSpec = RUN, said: str | None = "Building the part.") -> ToolCalls:
    return round_of(n, (spec, said))


class Model(Inference):
    """Answers each step from `script`; records each prompt, and the checkpoint last saved when it was asked."""

    def __init__(self, store: "Keeping") -> None:
        self.script: list[ToolCalls | Reply | Exception] = []
        self.asked: list[Prompt] = []
        self.saved_at_step: list[Checkpoint | None] = []
        self._store = store

    async def step(self, task: Task, prompt: Prompt, output: type[Any], *,
                   conversation_id: int | None = None) -> Any:
        self.asked.append(prompt)
        self.saved_at_step.append(loads(self._store.saved[-1]) if self._store.saved else None)
        got = self.script.pop(0)
        if isinstance(got, Exception):
            raise got
        return got if isinstance(got, ToolCalls) else output.model_validate(got.model_dump())

    async def generate(self, task: Task, prompt: Prompt, output: type[Any], *,
                       conversation_id: int | None = None) -> Any:
        raise AssertionError("a turn steps, it never generates")

    async def transcribe(self, task: SpeechTask, heard: Heard, *, conversation_id: int | None = None) -> Transcript:
        raise AssertionError("not used")

    async def speak(self, task: SpeechTask, text: str, *, conversation_id: int | None = None) -> Speech:
        raise AssertionError("not used")

    @property
    def choices(self) -> list[str]:
        return [p.tool_choice for p in self.asked]

    def last_text(self, step: int) -> str:
        last = self.asked[step].messages[-1]
        assert isinstance(last, Message)
        return last.text


class Keeping(NullInFlight):
    """An `InFlight` that keeps each saved checkpoint text."""

    def __init__(self) -> None:
        self.saved: list[str] = []

    async def begin(self, conversation_id: int, said_id: int, checkpoint: str) -> Claim:
        self.saved.append(checkpoint)
        return Claim(said_id, conversation_id, "h")

    async def save(self, claim: Claim, checkpoint: str) -> None:
        self.saved.append(checkpoint)

    def last(self) -> Checkpoint:
        return loads(self.saved[-1])


class Timed(Tools):
    """Each call moves `clock` on by its tool's seconds (or `default`) and is recorded as the tool saw it."""

    def __init__(self, clock: Clock, seconds: float | Mapping[str, float] = 0.0) -> None:
        self.clock = clock
        self.seconds = seconds
        self.called: list[ToolCall] = []

    async def catalogue(self) -> Catalogue:
        return Catalogue(TOOLS, None)

    async def call(self, call: ToolCall) -> ToolResult:
        self.called.append(call)
        self.clock.advance(self.seconds if isinstance(self.seconds, float | int) else self.seconds[call.name])
        return ToolResult(call.id, "ok")

    def changes(self) -> int:
        """Calls to a tool whose spec does not read."""
        reading = {t.name for t in TOOLS if t.reads}
        return sum(1 for c in self.called if c.name not in reading)


@dataclass
class Rig:
    model: Model
    clock: Clock
    store: Keeping

    def saved(self, base: Checkpoint | None = None) -> Saved:
        """Steps for a checkpointed turn that began with `base`."""
        return Saved(Claim(77, 5, "h"), base if base is not None else checkpoint())


@pytest.fixture
def rig() -> Generator[Rig]:
    store = Keeping()
    model = Model(store)
    services.register(Inference, model)
    services.register(InFlight, store)
    yield Rig(model, Clock(START), store)
    services.unregister(Inference)
    services.unregister(InFlight)


@dataclass
class Run:
    answer: Answer
    held: list[str]
    tools: Timed


async def drive(rig: Rig, limits: Limits, *, seconds: float | Mapping[str, float] = 0.0, hold: bool = True,
                steps: Steps = NO_STEPS, kind: Kind = "brainstorm", started: float = START) -> Run:
    """`answer`, then `resume` for each `Held`, until she answers: her held lines in order, and the tools."""
    tools = Timed(rig.clock, seconds)
    got = await answer(kind, SYSTEM, HISTORY, TOOLS, limits, CONVERSATION, hold=hold, source=tools, started=started,
                       clock=rig.clock, steps=steps)
    held: list[str] = []
    while isinstance(got, Held):
        held.append(got.reply.text)
        got = await resume(got, kind, SYSTEM, TOOLS, limits, CONVERSATION, source=tools, started=started,
                           clock=rig.clock, steps=steps)
    return Run(got, held, tools)
