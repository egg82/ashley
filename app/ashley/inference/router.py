"""The Inference implementation: the task's routes in order, each provider resting after it fails `unavailable`,
every call recorded in the spend ledger. Contract: `Inference`."""

import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import TypeVar

from pydantic import BaseModel

from .embed_router import EmbedCalls
from .embedding import EmbedRole, Embedded, EmbedTask
from .image import Aspect, Imaged
from .image_quota import ImageCap
from .image_router import ImageCalls
from .inference import Inference, InferenceCutOff, InferenceRefused, InferenceRejected, InferenceUnavailable
from .model import Prompt, Route, Task, ToolCalls, Usage
from .prices import Prices
from .provider import Failure, Provider, ProviderFailed, ProviderRefused, ToolUse, Wired
from .roster import Roster, utc_today
from .routes import TASKS, Routes
from .spend import Outcome, SpendLedger
from .speech import AudioFormat, Heard, Speech, SpeechTask, Transcript
from .speech_router import SpeechCalls
from .voiceprint import Voiceprint, VoiceprintTask
from .voiceprint_router import VoiceprintCalls

T = TypeVar("T", bound=BaseModel)


@dataclass
class Failed:
    """Why each route called in a walk failed, and whether any reply was cut off at the token limit."""

    kinds: list[Failure] = field(default_factory=list[Failure])
    cut_off: bool = False


class RoutedInference(Inference):
    def __init__(self, routes: Routes, providers: Iterable[Wired], ledger: SpendLedger, prices: Prices,
                 clock: Callable[[], float] = time.monotonic, today: Callable[[], date] = utc_today,
                 image_cap: ImageCap | None = None) -> None:
        """`providers` are the wired ones, by `Wired.name` (two with one name raise ValueError); a route naming any
        other is unwired. `clock` is monotonic seconds, for resting and for each call's duration; `today` is the UTC
        date a call is priced on; `image_cap` is what limits pictures, none meaning none may be drawn. Which providers are resting is held in this process only: a restarted pod tries
        each once again, which costs one failed call."""
        self._roster = Roster(routes, providers, ledger, prices, clock, today)
        self._speech = SpeechCalls(self._roster)
        self._embedding = EmbedCalls(self._roster)
        self._voiceprints = VoiceprintCalls(self._roster)
        self._images = ImageCalls(self._roster, image_cap)

    async def transcribe(self, task: SpeechTask, heard: Heard, *, conversation_id: int | None = None) -> Transcript:
        return await self._speech.transcribe(task, heard, conversation_id)

    async def speak(self, task: SpeechTask, text: str, *, conversation_id: int | None = None) -> Speech:
        return await self._speech.speak(task, text, conversation_id)

    async def warm(self, task: SpeechTask | EmbedTask | VoiceprintTask) -> None:
        if task == "embed":
            await self._embedding.warm()
        elif task == "voiceprint":
            await self._voiceprints.warm()
        else:
            await self._speech.warm(task)

    async def make_image(self, prompt: str, aspect: Aspect, *, household_id: int, conversation_id: int) -> Imaged:
        return await self._images.make(prompt, aspect, household_id, conversation_id)

    async def embed(self, texts: Sequence[str], role: EmbedRole, *, conversation_id: int | None = None) -> Embedded:
        return await self._embedding.embed(texts, role, conversation_id)

    async def voiceprint(self, format: AudioFormat, pcm: bytes, *, conversation_id: int | None = None) -> Voiceprint:
        return await self._voiceprints.voiceprint(format, pcm, conversation_id)

    async def step(self, task: Task, prompt: Prompt, output: type[T], *,
                   conversation_id: int | None = None) -> T | ToolCalls:
        _check_task(task)
        return await self._walk(task, prompt, output, conversation_id)

    async def generate(self, task: Task, prompt: Prompt, output: type[T], *, conversation_id: int | None = None) -> T:
        _check_task(task)
        if prompt.tools:
            raise ValueError("a prompt with tools is a step, not generate")
        answer = await self._walk(task, prompt, output, conversation_id)
        assert not isinstance(answer, ToolCalls), "a prompt offering no tools gets no tool calls past _attempt"
        return answer

    async def _walk(self, task: Task, prompt: Prompt, output: type[T],
                    conversation_id: int | None) -> T | ToolCalls:
        """The first answer from the task's routes in order, skipping unwired and resting ones. Raises
        InferenceRejected when every route called failed `error`, InferenceCutOff when a reply was cut off at the token
        limit, else InferenceUnavailable."""
        failures = Failed()
        for route, provider in self._roster.candidates(task, Provider):
            answer = await self._attempt(task, route, provider, prompt, output, conversation_id, failures)
            if answer is not None:
                return answer
        if failures.kinds and all(f == "error" for f in failures.kinds):
            raise InferenceRejected(f"every route rejected the request for task {task}")
        if failures.cut_off:
            raise InferenceCutOff(f"a reply was cut off at the token limit for task {task}")
        raise InferenceUnavailable(f"no route answered for task {task}")

    async def _attempt(self, task: Task, route: Route, provider: Provider, prompt: Prompt, output: type[T],
                       conversation_id: int | None, failures: Failed) -> T | ToolCalls | None:
        """The route's answer, None when it failed (the next route is tried, and `failures` gains why); InferenceRefused
        when it declined.
        Tool calls the prompt did not allow fail the call `invalid_output`."""
        started = self._roster.clock()
        try:
            completion = await provider.complete(
                route.model, route.params, prompt.system_for(route.variant), prompt.messages, prompt.tools,
                prompt.tool_choice, output, route.timeout_s)
        except ProviderRefused as e:
            await self._record(task, route, "refused", e.usage, started, conversation_id)
            raise InferenceRefused(f"{route.provider} declined to answer") from e
        except ProviderFailed as e:
            await self._record(task, route, e.failure, e.usage, started, conversation_id, reason=str(e))
            self._roster.failed(route, e.failure)
            failures.kinds.append(e.failure)
            failures.cut_off = failures.cut_off or e.cut_off
            return None
        if isinstance(completion, ToolUse):
            asked = len(completion.calls.calls)
            if not _allowed(prompt, completion.calls):
                await self._record(task, route, "invalid_output", completion.usage, started, conversation_id, asked)
                failures.kinds.append("invalid_output")
                return None
            await self._record(task, route, "ok", completion.usage, started, conversation_id, asked)
            return completion.calls
        await self._record(task, route, "ok", completion.usage, started, conversation_id)
        return completion.output

    async def _record(self, task: Task, route: Route, outcome: Outcome, usage: Usage | None, started: float,
                      conversation_id: int | None, tool_calls: int = 0, reason: str | None = None) -> None:
        await self._roster.record(task, route, outcome, usage, started,
                                  {"input_tokens": usage and usage.input_tokens,
                                   "output_tokens": usage and usage.output_tokens, "tool_calls": tool_calls},
                                  conversation_id, reason)


def _check_task(task: Task) -> None:
    if task not in TASKS:
        raise ValueError(f"unknown task: {task!r}")


def _allowed(prompt: Prompt, asked: ToolCalls) -> bool:
    """Whether the calls are ones the prompt let the model make: at least one, each naming an offered tool, ids
    unique, and not under tool choice `none`."""
    offered = {t.name for t in prompt.tools}
    ids = [c.id for c in asked.calls]
    return (bool(ids) and prompt.tool_choice != "none" and len(set(ids)) == len(ids)
            and all(c.name in offered for c in asked.calls))
