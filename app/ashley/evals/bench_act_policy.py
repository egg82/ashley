"""A scripted stand-in for the model, for `bench-act --scripted`: it checks the harness and the loop's mechanics (windows,
resume clock, holds, where the bench view and the open benches sit in the prompt) and says nothing about how the live
model behaves. Each policy acts on structure only: the tool choice, the step count and whether a section is in the
system prompt."""

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, TypeVar

from pydantic import BaseModel

from ..inference.embedding import EmbedRole, Embedded, EmbedTask
from ..inference.inference import Inference, InferenceUnavailable
from ..inference.model import Message, Prompt, Task, ToolCall, ToolCalls, ToolResults
from ..inference.reply import Reply
from ..inference.speech import AudioFormat, Heard, Speech, SpeechTask, Transcript
from ..inference.voiceprint import Voiceprint, VoiceprintTask

T = TypeVar("T", bound=BaseModel)
MODEL_PIECE = 6
BENCH_VIEW = "The bench as it stood"
OPEN_BENCHES = "Their open benches"


def reply(answers: bool = True) -> Reply:
    return Reply(answers=answers, spoken="Done.", text="Done.")


def call(name: str, step: int, **arguments: Any) -> ToolCalls:
    return ToolCalls((ToolCall(f"s{step}", name, {**arguments, "aside": "Working on it."}),))


@dataclass
class Scripted(Inference):
    """Answers each step from `policy` and how many steps came before it."""

    policy: str
    seen: list[Prompt] = field(default_factory=list[Prompt])
    piece: int = MODEL_PIECE

    async def step(self, task: Task, prompt: Prompt, output: type[T], *,
                   conversation_id: int | None = None) -> T | ToolCalls:
        self.seen.append(prompt)
        got = self._next(prompt, len(self.seen))
        return got if isinstance(got, ToolCalls) else output.model_validate(got.model_dump())

    def _next(self, prompt: Prompt, step: int) -> Reply | ToolCalls:
        moment = prompt.system["default"].moment
        if prompt.tool_choice == "none":
            return reply(answers=self.policy != "long_builder")
        if self.policy == "builder":
            return reply() if _ran(prompt, "bench_run") else call("bench_run", step, piece_id=MODEL_PIECE)
        if self.policy == "long_builder":
            return reply() if step > 5 else call("bench_run", step, piece_id=MODEL_PIECE)
        if self.policy == "editor":
            return reply() if _ran(prompt, "bench_edit") else call("bench_edit", step, piece_id=MODEL_PIECE)
        if self.policy == "mover":
            return self._mover(prompt, moment, step)
        if self.policy == "replay":
            return self._replayer(prompt, step)
        if BENCH_VIEW in moment or _ran(prompt, "bench_read"):
            return reply()
        return call("bench_read", step)

    def _mover(self, prompt: Prompt, moment: str, step: int) -> Reply | ToolCalls:
        if not _ran(prompt, "move_page"):
            return call("move_page", step, to="bench", bench_id=23) if OPEN_BENCHES in moment else reply()
        return reply() if _ran(prompt, "bench_run") else call("bench_run", step, piece_id=MODEL_PIECE)

    def _replayer(self, prompt: Prompt, step: int) -> Reply | ToolCalls:
        """Reads the piece, edits it once on the version read, runs the version the edit made, then answers."""
        version = _latest_version(prompt)
        if _ran(prompt, "bench_run"):
            return reply()
        if version is None:
            return call("bench_read_piece", step, piece_id=self.piece)
        if not _ran(prompt, "bench_edit"):
            return call("bench_edit", step, piece_id=self.piece, base_version=version, title="Model",
                        body=f"show(Box({step}, 1, 1))")
        return call("bench_run", step, piece_id=self.piece, base_version=version, language="build123d")

    async def generate(self, task: Task, prompt: Prompt, output: type[T], *, conversation_id: int | None = None) -> T:
        raise InferenceUnavailable("scripted: steps only")

    async def transcribe(self, task: SpeechTask, heard: Heard, *, conversation_id: int | None = None) -> Transcript:
        raise NotImplementedError

    async def speak(self, task: SpeechTask, text: str, *, conversation_id: int | None = None) -> Speech:
        raise NotImplementedError

    async def embed(self, texts: Sequence[str], role: EmbedRole, *, conversation_id: int | None = None) -> Embedded:
        raise InferenceUnavailable("scripted: steps only")

    async def voiceprint(self, format: AudioFormat, pcm: bytes, *, conversation_id: int | None = None) -> Voiceprint:
        raise NotImplementedError

    async def warm(self, task: SpeechTask | EmbedTask | VoiceprintTask) -> None:
        raise NotImplementedError


def _latest_version(prompt: Prompt) -> int | None:
    """The `version` in the newest tool result of this turn that carries one."""
    for entry in reversed(prompt.messages):
        if isinstance(entry, Message):
            return None
        for result in entry.results if isinstance(entry, ToolResults) else ():
            try:
                found = json.loads(result.content)
            except ValueError:
                continue
            loose: Any = found
            version: Any = dict[str, Any](loose).get("version") if isinstance(found, dict) else None
            if isinstance(version, int):
                return version
    return None


def _ran(prompt: Prompt, name: str) -> bool:
    return any(isinstance(e, ToolCalls) and any(c.name == name for c in e.calls) for e in prompt.messages)
