"""One wake on a satellite, carried to her answer heard in the room.

The events go to the device in the order Home Assistant's Assist pipeline sends them to an ESPHome satellite whose wake
word fired on the device (`homeassistant/components/esphome/assist_satellite.py`, and what ESPHome's
`voice_assistant` component does with each): run start; STT start; STT VAD start once speech starts; STT VAD end once it
stops, which turns the device's microphone off; STT end with the transcript; intent start; intent end with the
conversation id; TTS start with the text and TTS end with the clip's URL, which the device plays; run end. With a room
speaker the two TTS events are left out (a device with no TTS start goes back to idle at run end) and Home Assistant
plays the URL there instead; if Home Assistant refuses, the device plays it after all.

An empty transcript ends the run quietly: run end and nothing else. A pending reply (no words: her answer comes through
the outbox from the runner that finishes her turn) ends it after intent end, with nothing played. A failure sends an error event (`code`, `message`)
and run end: `stt-provider-unavailable` when no transcription route answered, `intent-failed` when her reply was refused
or unavailable, `tts-failed` when the clip could not be stored. Once there is a transcript, her voice's route is warmed
(`Inference.warm`) while the reply is made, so the clip's fetch finds a connection open. Before she is asked, the
voice's speaker step (`identify.Identify`) names who spoke, as the Inbound's `heard_as`, or no one.

Open screens are told through `Mark`: listening to the transcript, speaking from the reply's hand-over.

Logs `voice.run` once per run: device, outcome (`ok`, `room_speaker`, `empty`, `pending`, `aborted`, the failure's
reason, or `error` after `voice.run_error` with the traceback), clip id, `stt_provider` and `stt_model` (the route
that transcribed), and `wake_to_stt_end_ms` (speech plus the end-of-speech wait), `stt_ms` (end of speech to transcript) and `respond_ms`, each present only once reached. The clip
route logs `voice.clip` with the TTS route and timings. Never audio or text."""

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass

from aioesphomeapi.model import VoiceAssistantEventType as Event

from ... import logs, services
from ...inference.inference import Inference, InferenceUnavailable
from ...inference.speech import AudioFormat, Heard, Transcript
from ..model import Inbound, Outbound, Satellite
from ..respond import RespondRefused, RespondUnavailable
from .clips import Clips, ClipsUnavailable
from .config import EndOfSpeech, Playback
from .connection import Link
from .end_of_speech import Utterance
from .heard_as import MatchPolicy
from .identify import Identify
from .mark import Mark
from .vad import Detector, Frames

log = logging.getLogger("ashley.channels.voice")

Respond = Callable[[Inbound], Awaitable[Outbound]]
Play = Callable[[int, str, str], Awaitable[bool]]
"""Play a URL on a room speaker of a household's house (household id, entity id, URL); True once accepted."""

_MESSAGES = {
    "stt-provider-unavailable": "Speech recognition is unavailable",
    "intent-failed": "She could not answer",
    "tts-failed": "Her reply could not be prepared",
}


@dataclass(frozen=True)
class Pipeline:
    """What every run shares: where clip URLs point (`clip_base_url`, no trailing slash), the end-of-speech timings,
    the turn loop, the room-speaker player (None for none), a fresh VAD per run, the
    voice match's policy (`voice.json`'s `speaker`) and how long a reply is estimated to play."""

    clip_base_url: str
    end_of_speech: EndOfSpeech
    respond: Respond
    play: Play | None
    detector: Callable[[], Detector]
    speaker: MatchPolicy
    playback: Playback


class Run:
    """`audio` and `end_audio` feed the microphone in; `go` carries the run and returns when it has ended. Cancel the
    task running `go` to abandon it (the device aborted, or the connection went)."""

    def __init__(self, satellite: Satellite, link: Link, pipeline: Pipeline) -> None:
        self._satellite = satellite
        self._link = link
        self._pipeline = pipeline
        self._queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        self._woke = time.perf_counter()
        self._speech_ended: float | None = None
        self._ms: dict[str, int] = {}
        self._stt: dict[str, str] = {}
        self._clip: int | None = None
        self._warming: asyncio.Task[None] | None = None
        self._identify = Identify(satellite.device, pipeline.speaker)
        self._mark = Mark(satellite.device.household_id, pipeline.playback)

    def audio(self, data: bytes) -> None:
        self._queue.put_nowait(data)

    def end_audio(self) -> None:
        self._queue.put_nowait(None)

    async def go(self) -> None:
        outcome = "aborted"
        self._mark.listening()
        try:
            outcome = await self._carry()
        except Exception:
            outcome = "error"
            logs.error(log, "voice.run_error", exc=True, device=self._satellite.device.id)
        finally:
            self._mark.heard()
            self._identify.close()
            logs.info(log, "voice.run", device=self._satellite.device.id, outcome=outcome, clip=self._clip, **self._stt,
                      **self._ms)

    async def _carry(self) -> str:
        self._send(Event.VOICE_ASSISTANT_RUN_START)
        self._send(Event.VOICE_ASSISTANT_STT_START)
        try:
            transcript = await services.get(Inference).transcribe("transcribe", Heard(AudioFormat(), self._listen()))
        except InferenceUnavailable:
            return self._fail("stt-provider-unavailable", "stt_unavailable")
        self._stt_done(transcript)
        self._mark.heard()
        if not transcript.text:
            self._send(Event.VOICE_ASSISTANT_RUN_END)
            return "empty"
        self._send(Event.VOICE_ASSISTANT_STT_END, {"text": transcript.text})
        return await self._answer(transcript.text)

    async def _answer(self, text: str) -> str:
        self._send(Event.VOICE_ASSISTANT_INTENT_START)
        self._warming = asyncio.create_task(services.get(Inference).warm("speak"))
        heard_as = await self._identify.speaker()
        started = time.perf_counter()
        try:
            out = await self._pipeline.respond(self._inbound(text, heard_as))
        except RespondRefused:
            return self._fail("intent-failed", "refused")
        except RespondUnavailable:
            return self._fail("intent-failed", "respond_unavailable")
        self._ms["respond_ms"] = _ms_since(started)
        self._send(Event.VOICE_ASSISTANT_INTENT_END,
                   {"conversation_id": str(out.conversation_id), "continue_conversation": "0"})
        if not out.body:
            self._send(Event.VOICE_ASSISTANT_RUN_END)
            return "pending"
        try:
            clip = await services.get(Clips).add(self._satellite.device.id, out.body, _ms_since(self._woke))
        except ClipsUnavailable:
            return self._fail("tts-failed", "clips_unavailable")
        self._clip = clip.id
        return await self._deliver(out.body, f"{self._pipeline.clip_base_url}/api/voice/clips/{clip.token}")

    async def _deliver(self, body: str, url: str) -> str:
        speaker, play = self._satellite.room_speaker, self._pipeline.play
        if speaker is not None and play is not None:
            if await play(self._satellite.device.household_id, speaker, url):
                self._mark.speaking(body)
                self._send(Event.VOICE_ASSISTANT_RUN_END)
                return "room_speaker"
            logs.warning(log, "voice.room_speaker_failed", device=self._satellite.device.id)
        self._mark.speaking(body)
        self._send(Event.VOICE_ASSISTANT_TTS_START, {"text": body})
        self._send(Event.VOICE_ASSISTANT_TTS_END, {"url": url})
        self._send(Event.VOICE_ASSISTANT_RUN_END)
        return "ok"

    async def _listen(self) -> AsyncIterator[bytes]:
        """The microphone's chunks until end of speech or the end of the device's audio, whichever is first."""
        frames = Frames(self._pipeline.detector())
        utterance = Utterance(self._pipeline.end_of_speech)
        while (chunk := await self._queue.get()) is not None:
            self._identify.heard(chunk)
            yield chunk
            for probability in frames.probabilities(chunk):
                before = utterance.state
                after = utterance.frame(probability)
                if before == "waiting" and after == "speaking":
                    self._send(Event.VOICE_ASSISTANT_STT_VAD_START)
                if after == "ended":
                    self._speech_end()
                    self._send(Event.VOICE_ASSISTANT_STT_VAD_END)
                    return
        self._speech_end()

    def _speech_end(self) -> None:
        self._speech_ended = time.perf_counter()
        self._ms["wake_to_stt_end_ms"] = _ms_since(self._woke, self._speech_ended)
        self._identify.ended()

    def _stt_done(self, transcript: Transcript) -> None:
        self._stt = {"stt_provider": transcript.provider, "stt_model": transcript.model}
        if self._speech_ended is not None:
            self._ms["stt_ms"] = _ms_since(self._speech_ended)

    def _inbound(self, text: str, heard_as: int | None) -> Inbound:
        device = self._satellite.device
        return Inbound(household_id=device.household_id, thread=f"device:{device.id}", text=text, kind=device.kind,
                       medium="spoken", audience=device.audience, speaker_id=None, shared=True, place=device.place,
                       channel="voice", remembers=device.remembers, heard_as=heard_as, later=True, taint=None)

    def _fail(self, code: str, reason: str) -> str:
        self._send(Event.VOICE_ASSISTANT_ERROR, {"code": code, "message": _MESSAGES[code]})
        self._send(Event.VOICE_ASSISTANT_RUN_END)
        return reason

    def _send(self, event: Event, data: dict[str, str] | None = None) -> None:
        self._link.send_event(event, data)


def _ms_since(start: float, end: float | None = None) -> int:
    return int(((time.perf_counter() if end is None else end) - start) * 1000)
