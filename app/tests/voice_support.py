"""Fakes at the seams the voice adapter owns: the satellite connection (`Connection`), Inference's speech calls, the
turn loop, the room speaker and the VAD; and a satellite device row in a real database."""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import TypeVar

from aioesphomeapi.model import VoiceAssistantEventType as Event
from ashley.channels.model import Device, Inbound, Outbound, Satellite
from ashley.channels.voice.config import EndOfSpeech, Playback
from ashley.channels.voice.connection import OnAudio, OnStart, OnStop
from ashley.channels.voice.heard_as import MatchPolicy
from ashley.channels.voice.run import Pipeline
from ashley.inference.embedding import EmbedTask
from ashley.inference.inference import Inference
from ashley.inference.model import Prompt, Task, ToolCalls
from ashley.inference.speech import Heard, Speech, SpeechTask, Transcript
from ashley.inference.voiceprint import VoiceprintTask
from contract.conversations_support import scalar
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)
TIMINGS = EndOfSpeech(start_probability=0.2, speech_probability=0.5, speech_ms=30, start_gap_ms=50, silence_ms=50,
                      max_utterance_ms=2000)
FRAME = b"\x01\x00" * 160   # 10 ms of 16 kHz 16-bit mono
SPEECH, QUIET = 0.9, 0.1
LOGS_ONLY = MatchPolicy(floor=0.5, margin=0.1, min_audio_ms=50, decides=False)


def satellite_row(url: str, household_id: int, host: str = "10.0.0.9", room_speaker: str | None = None,
                  name: str = "office echo") -> Satellite:
    """A device row that is a satellite, and the Satellite it reads back as."""
    device_id = int(scalar(url, "INSERT INTO devices (household_id, name, place, audience, medium, kind, token_sha256, "
                                "esphome_host, room_speaker) VALUES (%s, %s, 'office', 'present', 'spoken', 'command', "
                                "sha256(%s::bytea), %s, %s) RETURNING id",
                           (household_id, name, name.encode(), host, room_speaker)))
    return Satellite(Device(device_id, household_id, name, "office", "present", "spoken", "command"), host,
                     room_speaker)


@dataclass
class FakeLink:
    """Records every event sent, as (event, data)."""

    sent: list[tuple[Event, dict[str, str] | None]] = field(default_factory=list[tuple[Event, dict[str, str] | None]])

    def send_event(self, event: Event, data: dict[str, str] | None) -> None:
        self.sent.append((event, data))

    def kinds(self) -> list[Event]:
        return [e for e, _ in self.sent]

    def data(self, event: Event) -> dict[str, str] | None:
        return next(d for e, d in self.sent if e == event)


@dataclass
class FakeConnection(FakeLink):
    """A satellite session. `failures` connect attempts raise before one succeeds; `lose()` ends the session as the
    device would; the handlers the code subscribed are kept so a test can play the device."""

    failures: list[Exception] = field(default_factory=list[Exception])
    connects: int = 0
    disconnects: int = 0
    on_lost: Callable[[], Awaitable[None]] | None = None
    handlers: tuple[OnStart, OnAudio, OnStop] | None = None
    announced: list[str] = field(default_factory=list[str])
    has_player: bool = True

    def announce(self, url: str) -> bool:
        if self.has_player:
            self.announced.append(url)
        return self.has_player

    async def connect(self, on_lost: Callable[[], Awaitable[None]]) -> None:
        self.connects += 1
        if self.failures:
            raise self.failures.pop(0)
        self.on_lost = on_lost

    def subscribe_voice(self, on_start: OnStart, on_audio: OnAudio, on_stop: OnStop) -> None:
        self.handlers = (on_start, on_audio, on_stop)

    async def disconnect(self) -> None:
        self.disconnects += 1

    async def lose(self) -> None:
        assert self.on_lost is not None
        await self.on_lost()


class Scripted:
    """A VAD that answers the next scripted probability per frame, then `QUIET`."""

    def __init__(self, probabilities: list[float]) -> None:
        self._left = list(probabilities)

    def process_10ms(self, audio: bytes) -> float:
        assert len(audio) == 320
        return self._left.pop(0) if self._left else QUIET


@dataclass
class FakeSpeech(Inference):
    """`transcribe` reads the utterance to its end and answers `transcript` (or raises it); `speak` answers `audio` in
    two chunks (or raises it). Text calls are not used here."""

    transcript: str | Exception = "what time is it"
    audio: bytes | Exception = b"ID3-audio-bytes"
    heard: list[bytes] = field(default_factory=list[bytes])
    spoken: list[str] = field(default_factory=list[str])
    warmed: list[SpeechTask | EmbedTask | VoiceprintTask] = field(
        default_factory=list[SpeechTask | EmbedTask | VoiceprintTask])

    async def generate(self, task: Task, prompt: Prompt, output: type[T], *, conversation_id: int | None = None) -> T:
        raise AssertionError("not used")

    async def step(self, task: Task, prompt: Prompt, output: type[T], *,
                   conversation_id: int | None = None) -> T | ToolCalls:
        raise AssertionError("not used")

    async def transcribe(self, task: SpeechTask, heard: Heard, *, conversation_id: int | None = None) -> Transcript:
        assert task == "transcribe"
        self.heard = [chunk async for chunk in heard.chunks]
        if isinstance(self.transcript, Exception):
            raise self.transcript
        return Transcript(self.transcript, "fake", "fake-stt")

    async def warm(self, task: SpeechTask | EmbedTask | VoiceprintTask) -> None:
        self.warmed.append(task)

    async def speak(self, task: SpeechTask, text: str, *, conversation_id: int | None = None) -> Speech:
        assert task == "speak"
        self.spoken.append(text)
        if isinstance(self.audio, Exception):
            raise self.audio
        audio = self.audio

        async def chunks() -> AsyncIterator[bytes]:
            yield audio[:3]
            yield audio[3:]

        return Speech("audio/mpeg", chunks(), "fake", "fake-tts")


@dataclass
class FakeTurnLoop:
    """`respond`: records the Inbound and answers `body` (`follows` as given) in conversation 41, or raises `error`."""

    body: str = "It is noon."
    error: Exception | None = None
    asked: list[Inbound] = field(default_factory=list[Inbound])
    follows: bool = False

    async def __call__(self, inbound: Inbound) -> Outbound:
        self.asked.append(inbound)
        if self.error is not None:
            raise self.error
        return Outbound(41, "spoken", self.body, follows=self.follows)


@dataclass
class FakeSpeaker:
    """A room speaker player: records (entity, url), and the household each was played in, and answers `accepts`."""

    accepts: bool = True
    played: list[tuple[str, str]] = field(default_factory=list[tuple[str, str]])
    households: list[int] = field(default_factory=list[int])

    async def __call__(self, household_id: int, entity_id: str, url: str) -> bool:
        self.households.append(household_id)
        self.played.append((entity_id, url))
        return self.accepts


def pipeline(loop: FakeTurnLoop, speaker: FakeSpeaker | None = None,
             probabilities: list[float] | None = None, policy: MatchPolicy = LOGS_ONLY) -> Pipeline:
    """Speech for 3 frames then quiet, unless `probabilities` says otherwise."""
    script = [SPEECH] * 3 if probabilities is None else probabilities
    return Pipeline("https://ashley.test", TIMINGS, loop, speaker, lambda: Scripted(script), policy,
                    Playback(0.0, 1000.0))


async def settle() -> None:
    for _ in range(20):
        await asyncio.sleep(0)
