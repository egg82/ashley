"""What makes the house eval safe and measurable: `GuardedTools`, which lets only the tools on the read allow-list
(`house_reads.json`) reach the house and answers every other call as done without reaching it, and `RecordingInference`, which
notes each model step of a reply so the harness can count rounds and see whether the step limit was reached."""

import json
from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from typing import TypeVar

from pydantic import BaseModel

from ..inference.embedding import EmbedRole, Embedded, EmbedTask
from ..inference.inference import Inference
from ..inference.model import Prompt, Task, ToolCall, ToolCalls, ToolResult
from ..inference.speech import AudioFormat, Heard, Speech, SpeechTask, Transcript
from ..inference.voiceprint import Voiceprint, VoiceprintTask
from ..tools.tools import Catalogue, Tools

T = TypeVar("T", bound=BaseModel)

DONE = json.dumps({"done": True, "changed": [{"state": "as asked"}]})


@dataclass(frozen=True)
class Attempt:
    """A call kept from the house because its tool is not on the allow-list: the tool and the arguments she gave."""

    name: str
    arguments: str


@dataclass
class GuardedTools(Tools):
    """`inner`'s catalogue unchanged, so she sees every tool she would, but `call` runs only a name in `reads`.
    Anything else is noted in `refused`, whatever the case expects, and answered with `DONE`, the shape of
    `house_do`'s result for an action that changed nothing visible, so she takes the action as done and does not retry it
    until the step limit."""

    inner: Tools
    reads: Collection[str]
    refused: list[Attempt] = field(default_factory=list[Attempt])
    ran: list[str] = field(default_factory=list[str])

    async def catalogue(self) -> Catalogue:
        return await self.inner.catalogue()

    async def call(self, call: ToolCall) -> ToolResult:
        if call.name not in self.reads:
            self.refused.append(Attempt(call.name, json.dumps(call.arguments, sort_keys=True, default=str)))
            return ToolResult(call.id, DONE)
        self.ran.append(call.name)
        return await self.inner.call(call)


@dataclass(frozen=True)
class Step:
    """One model step of a reply: its tool choice, the conversation, and the tools it asked for (empty for a reply)."""

    task: str
    choice: str
    conversation_id: int | None
    asked: tuple[ToolCall, ...]


@dataclass
class RecordingInference(Inference):
    """`inner` unchanged, every `step` noted in `steps`."""

    inner: Inference
    steps: list[Step] = field(default_factory=list[Step])

    async def step(self, task: Task, prompt: Prompt, output: type[T], *,
                   conversation_id: int | None = None) -> T | ToolCalls:
        got = await self.inner.step(task, prompt, output, conversation_id=conversation_id)
        self.steps.append(Step(task, prompt.tool_choice, conversation_id, got.calls if isinstance(got, ToolCalls) else ()))
        return got

    async def generate(self, task: Task, prompt: Prompt, output: type[T], *, conversation_id: int | None = None) -> T:
        return await self.inner.generate(task, prompt, output, conversation_id=conversation_id)

    async def transcribe(self, task: SpeechTask, heard: Heard, *, conversation_id: int | None = None) -> Transcript:
        return await self.inner.transcribe(task, heard, conversation_id=conversation_id)

    async def speak(self, task: SpeechTask, text: str, *, conversation_id: int | None = None) -> Speech:
        return await self.inner.speak(task, text, conversation_id=conversation_id)

    async def embed(self, texts: Sequence[str], role: EmbedRole, *, conversation_id: int | None = None) -> Embedded:
        return await self.inner.embed(texts, role, conversation_id=conversation_id)

    async def voiceprint(self, format: AudioFormat, pcm: bytes, *, conversation_id: int | None = None) -> Voiceprint:
        return await self.inner.voiceprint(format, pcm, conversation_id=conversation_id)

    async def warm(self, task: SpeechTask | EmbedTask | VoiceprintTask) -> None:
        await self.inner.warm(task)
