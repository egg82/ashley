"""The speech half of `RoutedInference`: the task's routes in order, each call recorded in the spend ledger. Contract:
`Inference.transcribe` and `Inference.speak`."""

import logging
from collections.abc import AsyncIterator

from .inference import InferenceUnavailable
from .model import Route, Usage
from .provider import ProviderFailed
from .roster import Roster
from .spend import Outcome
from .speech import Heard, Speech, SpeechTask, Transcript
from .speech_provider import Speaker, SpeechStream, Transcriber
from .utterance import Utterance

log = logging.getLogger("ashley.inference")


class SpeechCalls:
    def __init__(self, roster: Roster) -> None:
        self._roster = roster

    async def transcribe(self, task: SpeechTask, heard: Heard, conversation_id: int | None = None) -> Transcript:
        if task != "transcribe":
            raise ValueError(f"not a transcription task: {task!r}")
        utterance = Utterance(heard)
        for route, provider in self._roster.candidates(task, Transcriber):
            started = self._roster.clock()
            try:
                text = await provider.transcribe(route.model, route.params, heard.format, utterance.chunks(),
                                                 route.timeout_s, heard.language)
                await utterance.drain()
            except ProviderFailed as e:
                _raise_unless_provider_fault(utterance)
                await self._record_listen(task, route, e.failure, utterance, started, conversation_id, str(e))
                self._roster.failed(route, e.failure)
                continue
            _raise_unless_provider_fault(utterance)
            await self._record_listen(task, route, "ok", utterance, started, conversation_id)
            return Transcript(text.strip(), route.provider, route.model)
        await utterance.drain()
        raise InferenceUnavailable(f"no route answered for task {task}")

    async def _record_listen(self, task: SpeechTask, route: Route, outcome: Outcome, utterance: Utterance,
                             started: float, conversation_id: int | None, reason: str | None = None) -> None:
        audio_ms = utterance.duration_ms
        await self._roster.record(task, route, outcome, Usage(0, 0, audio_ms=audio_ms), started,
                                  {"audio_ms": audio_ms}, conversation_id, reason)

    async def speak(self, task: SpeechTask, text: str, conversation_id: int | None = None) -> Speech:
        if task != "speak" or not text:
            raise ValueError("speak takes the speak task and non-empty text")
        for route, provider in self._roster.candidates(task, Speaker):
            started = self._roster.clock()
            try:
                stream = await provider.speak(route.model, route.params, text, route.timeout_s)
            except ProviderFailed as e:
                await self._record_speech(task, route, e.failure, len(text), started, conversation_id, str(e))
                self._roster.failed(route, e.failure)
                continue
            return Speech(stream.media_type, self._relay(task, route, stream, len(text), started, conversation_id),
                          route.provider, route.model)
        raise InferenceUnavailable(f"no route started for task {task}")

    async def warm(self, task: SpeechTask) -> None:
        if task != "speak":
            raise ValueError(f"only speech is warmed: {task!r}")
        for route, provider in self._roster.candidates(task, Speaker):
            await self._roster.warm(task, route, provider.warm(route.timeout_s))
            return

    async def _relay(self, task: SpeechTask, route: Route, stream: SpeechStream, characters: int, started: float,
                     conversation_id: int | None) -> AsyncIterator[bytes]:
        outcome: Outcome = "ok"
        reason: str | None = None
        try:
            async for chunk in stream.chunks:
                yield chunk
        except ProviderFailed as e:
            outcome = e.failure
            reason = str(e)
        except Exception as e:
            outcome = "error"
            reason = type(e).__name__
        finally:
            await stream.close()
            self._roster.failed(route, outcome)
            await self._record_speech(task, route, outcome, characters, started, conversation_id, reason)

    async def _record_speech(self, task: SpeechTask, route: Route, outcome: Outcome, characters: int, started: float,
                             conversation_id: int | None, reason: str | None = None) -> None:
        await self._roster.record(task, route, outcome, Usage(0, 0, characters=characters), started,
                                  {"characters": characters}, conversation_id, reason)


def _raise_unless_provider_fault(utterance: Utterance) -> None:
    """The person's audio source broke: no provider is to blame, and no other route can finish the utterance."""
    if utterance.error is not None:
        raise utterance.error
