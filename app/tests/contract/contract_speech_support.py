"""Helpers for the blind speech contract tests: scripted fake speech providers over `inference_support`'s fake clock
and ledger, utterances that count how much of them was read, and a router whose table carries the speech tasks.

The fakes implement `Transcriber` and `Speaker` of `ashley.inference.speech_provider`."""

from collections.abc import AsyncIterator, Iterable, Mapping
from dataclasses import dataclass
from typing import Literal, get_args

from ashley.inference.model import Route, Task
from ashley.inference.provider import Failure, ProviderFailed, Wired
from ashley.inference.router import RoutedInference
from ashley.inference.spend import Call
from ashley.inference.routes import Routes
from ashley.inference.speech import AudioFormat, Heard, Speech
from ashley.inference.speech_provider import Speaker, SpeechStream, Transcriber
from inference_support import PRICES, TODAY, Clock, FakeLedger

MARK = "zqSPOKEN9031"
FORMAT = AudioFormat(rate=16000, width=2, channels=1)
CHUNKS = [b"\x01\x00" * 8000, b"\x02\x00" * 8000, b"\x03\x00" * 8000, b"\x04\x00" * 8000, b"\x05\x00" * 8000]
"""Five half-second chunks: 2.5 s at `FORMAT`."""
CHUNKS_MS = 2500


class Utterance:
    """Chunks that count how many have been handed out, so a test can tell reading as they arrive from reading ahead."""

    def __init__(self, chunks: Iterable[bytes] = CHUNKS, fmt: AudioFormat = FORMAT) -> None:
        self._chunks = list(chunks)
        self._format = fmt
        self.pulled = 0

    @property
    def pcm(self) -> bytes:
        return b"".join(self._chunks)

    @property
    def heard(self) -> Heard:
        return Heard(self._format, self._iterate())

    async def _iterate(self) -> AsyncIterator[bytes]:
        for chunk in self._chunks:
            self.pulled += 1
            yield chunk


@dataclass(frozen=True)
class Hear:
    """What one scripted `transcribe` does: read `read` chunks (all when None), take `seconds` on the clock, then
    return `text` or raise `error`."""

    text: str = "hello there"
    read: int | None = None
    error: ProviderFailed | None = None
    seconds: float = 0.0


@dataclass(frozen=True)
class Say:
    """What one scripted `speak` does: after `seconds`, fail at `where` (`call` and `first`: before the first bytes
    arrive, so `speak` itself raises, as `Speaker.speak` requires; `after`: once every chunk was delivered) or
    deliver `chunks` as `media_type`."""

    chunks: tuple[bytes, ...] = (b"RIFF", b"-voice", b"-more")
    media_type: str = "audio/wav"
    error: ProviderFailed | None = None
    where: Literal["call", "first", "after"] = "call"
    seconds: float = 0.0


def hear_fail(failure: Failure, read: int | None = None) -> Hear:
    return Hear(error=ProviderFailed(failure, f"{failure} (status 000)", None), read=read)


def say_fail(failure: Failure, where: Literal["call", "first", "after"] = "call") -> Say:
    return Say(error=ProviderFailed(failure, f"{failure} (status 000)", None), where=where)


@dataclass(frozen=True)
class Heard1:
    """One `transcribe` call as a provider received it."""

    model: str
    params: Mapping[str, object]
    timeout_s: float
    format: AudioFormat
    pcm: bytes


@dataclass(frozen=True)
class Said1:
    """One `speak` call as a provider received it."""

    model: str
    params: Mapping[str, object]
    text: str
    timeout_s: float


class FakeSpeechProvider(Transcriber, Speaker):
    """Plays `hears` / `says` one per call (the last repeats), moving the clock as the step says. `warm` records the
    timeout it was given, takes `warm_seconds` on the clock, then raises `warm_error` if one is set."""

    def __init__(self, name: str, hears: Iterable[Hear] = (), says: Iterable[Say] = (),
                 clock: Clock | None = None, watching: Utterance | None = None,
                 warm_error: Exception | None = None, warm_seconds: float = 0.0) -> None:
        self._name = name
        self._hears = list(hears) or [Hear()]
        self._says = list(says) or [Say()]
        self._clock = clock
        self._watching = watching
        self.heard: list[Heard1] = []
        self.said: list[Said1] = []
        self.pulled_when_done: list[int] = []
        self.warmed: list[float] = []
        self._warm_error = warm_error
        self._warm_seconds = warm_seconds

    @property
    def name(self) -> str:
        return self._name

    def check_transcribe_params(self, params: Mapping[str, object]) -> None:
        return None

    def check_speak_params(self, params: Mapping[str, object]) -> None:
        return None

    async def transcribe(self, model: str, params: Mapping[str, object], format: AudioFormat,
                         chunks: AsyncIterator[bytes], timeout_s: float) -> str:
        step = self._hears[min(len(self.heard) + 1, len(self._hears)) - 1]
        received = bytearray()
        taken = 0
        async for chunk in chunks:
            received += chunk
            taken += 1
            if step.read is not None and taken >= step.read:
                break
        self.heard.append(Heard1(model, params, timeout_s, format, bytes(received)))
        if self._watching is not None:
            self.pulled_when_done.append(self._watching.pulled)
        if self._clock is not None:
            self._clock.advance(step.seconds)
        if step.error is not None:
            raise step.error
        return step.text

    async def speak(self, model: str, params: Mapping[str, object], text: str, timeout_s: float) -> SpeechStream:
        step = self._says[min(len(self.said) + 1, len(self._says)) - 1]
        self.said.append(Said1(model, params, text, timeout_s))
        if self._clock is not None:
            self._clock.advance(step.seconds)
        if step.error is not None and step.where != "after":
            raise step.error
        return SpeechStream(step.media_type, self._deliver(step), self._close)

    async def warm(self, timeout_s: float) -> None:
        self.warmed.append(timeout_s)
        if self._clock is not None:
            self._clock.advance(self._warm_seconds)
        if self._warm_error is not None:
            raise self._warm_error

    async def _close(self) -> None:
        return None

    async def _deliver(self, step: Say) -> AsyncIterator[bytes]:
        for chunk in step.chunks:
            yield chunk
        if step.error is not None and step.where == "after":
            raise step.error


def speech_table(routes: Iterable[Route], cooldown_s: float = 300.0) -> Routes:
    """Every task, text and speech alike, gets `routes`."""
    given = tuple(routes)
    by_task: dict[Task, tuple[Route, ...]] = {k: given for k in get_args(Task)}
    return Routes(by_task, cooldown_s, {"transcribe": given, "speak": given})


def speech_router(routes: Iterable[Route], providers: Iterable[Wired], ledger: FakeLedger | None = None,
                  clock: Clock | None = None) -> RoutedInference:
    return RoutedInference(speech_table(routes), providers, ledger if ledger is not None else FakeLedger(), PRICES,
                           clock if clock is not None else Clock(), lambda: TODAY)


async def drain(speech: Speech) -> bytes:
    """Everything a played `Speech` delivers, until it ends or fails."""
    got = bytearray()
    async for chunk in speech.chunks:
        got += chunk
    return bytes(got)



def usage_of(row: Call, name: Literal["audio_ms", "characters"]) -> object:
    """A usage field of the speech contract (`audio_ms`, `characters`) on a spend row; fails when the row has no usage."""
    assert row.usage is not None, "a speech call's row carries its usage"
    return getattr(row.usage, name)
