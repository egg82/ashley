"""Stand-ins for the speech tests: a Wyoming server on a local port, scripted speech providers, an in-memory spend
ledger and a router assembled over them. Nothing here reaches a real provider."""

import asyncio
from collections.abc import AsyncIterator, Coroutine, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any, get_args

from ashley.inference.model import Route, Task, Usage
from ashley.inference.prices import Prices
from ashley.inference.provider import Failure, ProviderFailed
from ashley.inference.router import RoutedInference
from ashley.inference.routes import Routes
from ashley.inference.spend import Call, SpendLedger
from ashley.inference.speech import AudioFormat, Heard, SpeechTask
from ashley.inference.speech_provider import Speaker, SpeechStream, Transcriber
from wyoming.asr import Transcribe, Transcript
from wyoming.audio import AudioChunk, AudioStart, AudioStop
from wyoming.event import Event, async_read_event, async_write_event

FORMAT = AudioFormat(16000, 2, 1)
PCM = [b"\x01\x00" * 800, b"\x02\x00" * 800, b"\x03\x00" * 800]
"""Three 50 ms chunks."""
MS = 150


def run[R](scenario: Coroutine[Any, Any, R], limit: float = 10.0) -> R:
    async def bounded() -> R:
        return await asyncio.wait_for(scenario, limit)

    return asyncio.run(bounded())


async def pcm(chunks: Iterable[bytes] = PCM, gate: asyncio.Event | None = None) -> AsyncIterator[bytes]:
    """The utterance, one chunk after another; with `gate`, the last chunk waits until it is set."""
    parts = list(chunks)
    for i, chunk in enumerate(parts):
        if gate is not None and i == len(parts) - 1:
            await gate.wait()
        yield chunk


def heard(chunks: Iterable[bytes] = PCM, gate: asyncio.Event | None = None) -> Heard:
    return Heard(FORMAT, pcm(chunks, gate))


class WyomingServer:
    """Records what a client sends and answers `reply` after `AudioStop`: a transcript, `None` to hang up without one,
    or `silent` to say nothing at all."""

    def __init__(self, reply: str | None = "hello there", silent: bool = False) -> None:
        self.reply = reply
        self.silent = silent
        self.events: list[Event] = []
        self.first_chunk = asyncio.Event()
        self._server: asyncio.Server | None = None

    async def __aenter__(self) -> "WyomingServer":
        self._server = await asyncio.start_server(self._serve, "127.0.0.1", 0)
        return self

    async def __aexit__(self, *_: object) -> None:
        assert self._server is not None
        self._server.close()
        await self._server.wait_closed()

    @property
    def uri(self) -> str:
        assert self._server is not None
        return f"tcp://127.0.0.1:{self._server.sockets[0].getsockname()[1]}"

    async def _serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            while (event := await async_read_event(reader)) is not None:
                self.events.append(event)
                if AudioChunk.is_type(event.type):
                    self.first_chunk.set()
                if AudioStop.is_type(event.type):
                    if self.reply is not None and not self.silent:
                        await async_write_event(Transcript(self.reply).event(), writer)
                    if self.reply is None:
                        break
        finally:
            writer.close()

    def sent(self, kind: type[Transcribe] | type[AudioStart] | type[AudioChunk] | type[AudioStop]) -> list[Event]:
        return [e for e in self.events if kind.is_type(e.type)]


def failing(failure: Failure = "unavailable") -> ProviderFailed:
    return ProviderFailed(failure, f"{failure} (scripted)")


class MemoryLedger(SpendLedger):
    def __init__(self) -> None:
        self.calls: list[Call] = []

    async def record(self, call: Call) -> None:
        self.calls.append(call)


@dataclass
class ScriptedTranscriber(Transcriber):
    """Reads `read` chunks (None: all), then returns `text` or raises `error`. Keeps the chunks it saw."""

    label: str
    text: str = "scripted"
    error: ProviderFailed | None = None
    read: int | None = None
    seen: list[bytes] = field(default_factory=list[bytes])

    @property
    def name(self) -> str:
        return self.label

    def check_transcribe_params(self, params: Any) -> None:
        return None

    async def transcribe(self, model: str, params: Any, format: AudioFormat, chunks: AsyncIterator[bytes],
                         timeout_s: float) -> str:
        try:
            async for chunk in chunks:
                self.seen.append(chunk)
                if self.read is not None and len(self.seen) >= self.read:
                    break
        except Exception as e:
            raise ProviderFailed("error", type(e).__name__) from e
        if self.error is not None:
            raise self.error
        return self.text


@dataclass
class ScriptedSpeaker(Speaker):
    """Starts with `parts` (the first is held back until the call returns, like a real first byte), then breaks off
    with `after` when set; or raises `error` before starting."""

    label: str
    parts: Sequence[bytes] = (b"ab", b"cd")
    error: ProviderFailed | None = None
    after: ProviderFailed | None = None
    closed: int = 0

    @property
    def name(self) -> str:
        return self.label

    def check_speak_params(self, params: Any) -> None:
        return None

    async def speak(self, model: str, params: Any, text: str, timeout_s: float) -> SpeechStream:
        if self.error is not None:
            raise self.error
        return SpeechStream("audio/mpeg", self._chunks(), self._close)

    async def _chunks(self) -> AsyncIterator[bytes]:
        for part in self.parts:
            yield part
        if self.after is not None:
            raise self.after

    async def _close(self) -> None:
        self.closed += 1


def routes_for(task: SpeechTask, *names: str) -> Routes:
    text: dict[Task, tuple[Route, ...]] = {t: (Route("none", "m", 1.0),) for t in get_args(Task)}
    return Routes(text, 300.0, {task: tuple(Route(n, f"{n}-model", 5.0) for n in names)})


def router(task: SpeechTask, *providers: Transcriber | Speaker, ledger: MemoryLedger | None = None,
           names: Sequence[str] | None = None) -> tuple[RoutedInference, MemoryLedger]:
    ledger = ledger or MemoryLedger()
    chosen = tuple(names) if names is not None else tuple(p.name for p in providers)
    inference = RoutedInference(routes_for(task, *chosen), providers, ledger, Prices({}),
                                today=lambda: date(2026, 10, 25))
    return inference, ledger


def usage_of(call: Call) -> Usage:
    assert call.usage is not None
    return call.usage
