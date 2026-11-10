"""Fakes for the wake-turn tests: a scripted model that can hang as a killed runner's turn does, a switchboard of two
tools that records what reached it, and presence that knows nobody."""

import asyncio
from dataclasses import dataclass, field
from typing import Any

from ashley.inference.inference import Inference
from ashley.inference.model import Prompt, Task, ToolCall, ToolCalls, ToolResult, ToolSpec
from ashley.inference.reply import Reply
from ashley.inference.speech import Heard, Speech, SpeechTask, Transcript
from ashley.senses.presence import Presence
from ashley.tools.tools import Catalogue, Tools

LOOK = ToolSpec("look", "see something", {"type": "object"}, reads=True)
SWITCH = ToolSpec("switch", "turn something on", {"type": "object"}, reads=False)


@dataclass
class Model(Inference):
    """Answers each step from `script`; `prompts` is what each step was sent. With `hang` set it waits forever once the
    script is spent, as a turn does while its runner is killed, setting `reached` as it starts waiting."""

    script: list[ToolCalls | Reply | Exception] = field(default_factory=list[ToolCalls | Reply | Exception])
    prompts: list[Prompt] = field(default_factory=list[Prompt])
    hang: bool = False
    reached: asyncio.Event = field(default_factory=asyncio.Event)

    async def step(self, task: Task, prompt: Prompt, output: type[Any], *,
                   conversation_id: int | None = None) -> Any:
        if self.hang and not self.script:
            self.reached.set()
            await asyncio.sleep(3600)
        self.prompts.append(prompt)
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


@dataclass
class Switchboard(Tools):
    """`ran` is every call that reached a tool."""

    ran: list[ToolCall] = field(default_factory=list[ToolCall])

    async def catalogue(self) -> Catalogue:
        return Catalogue((LOOK, SWITCH), "")

    async def call(self, call: ToolCall) -> ToolResult:
        self.ran.append(call)
        return ToolResult(call.id, f'{{"ran": "{call.name}"}}')


class Nobody(Presence):
    async def home(self, household_id: int) -> frozenset[int] | None:
        return None
