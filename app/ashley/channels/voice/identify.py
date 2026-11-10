"""Whose voice one wake is, for `Run` (`decisions.md`, "A voice names the speaker as a hint").

The utterance's PCM is kept in memory for the run only. Once the utterance ends, its voiceprint and the reads a match
needs (the household's prints by that model, and presence) start, so they run while transcription finishes; `speaker`,
called only for a wake with words, awaits them. An armed device then stores the print (`Voices.enrol`) and names no
one, so a wake with no words never spends an enrolment; otherwise the print is matched (`heard_as.match`) and names the
person only when `MatchPolicy.decides`. A failure names no one and never fails the wake.

Logs `voice.speaker` once per wake that asked: device, outcome (an `heard_as.Outcome`, `enrolled`, `unavailable` when
inference or the store could not answer, or `error` after `voice.speaker_error` with the traceback), decides,
`voiceprint_ms` once a print was made, `remaining` for an enrolment, and for a match `best` and `second` to 2
decimals, `people` scored and `presence` agreement. Never who was named or enrolled, the audio or the vector."""

import asyncio
import logging
import time
from dataclasses import dataclass

from ... import logs, services
from ...inference.inference import Inference, InferenceUnavailable
from ...inference.speech import AudioFormat
from ...inference.voiceprint import Voiceprint
from ...senses.presence import Presence
from ..model import Device
from .heard_as import MatchPolicy, match
from .voices import PersonPrints, Voices, VoicesUnavailable

log = logging.getLogger("ashley.channels.voice")

_FORMAT = AudioFormat()


@dataclass(frozen=True)
class _Read:
    voiceprint: Voiceprint
    prints: tuple[PersonPrints, ...]
    home: frozenset[int] | None


class Identify:
    """One run's speaker step: `heard` each chunk of the utterance, `ended` once it ends, then `speaker` once; `close`
    when the run ends, whatever happened."""

    def __init__(self, device: Device, policy: MatchPolicy) -> None:
        self._device = device
        self._policy = policy
        self._pcm = bytearray()
        self._reading: asyncio.Task[_Read] | None = None
        self._fields: dict[str, object] = {}

    def heard(self, chunk: bytes) -> None:
        if self._reading is None:
            self._pcm += chunk

    def ended(self) -> asyncio.Task[_Read]:
        if self._reading is None:
            whole = len(self._pcm) - len(self._pcm) % _FORMAT.frame_bytes
            self._reading = asyncio.create_task(self._read(bytes(self._pcm[:whole])))
            self._pcm = bytearray()
        return self._reading

    async def speaker(self) -> int | None:
        """The person the voice names for the Inbound's `heard_as`, or None."""
        person_id: int | None = None
        try:
            person_id = await self._decide(await self.ended())
        except (InferenceUnavailable, VoicesUnavailable, TimeoutError):
            self._fields["outcome"] = "unavailable"
        except Exception:
            self._fields["outcome"] = "error"
            logs.error(log, "voice.speaker_error", exc=True, device=self._device.id)
        logs.info(log, "voice.speaker", device=self._device.id, decides=self._policy.decides, **self._fields)
        return person_id

    def close(self) -> None:
        if self._reading is not None:
            self._reading.cancel()
            if self._reading.done() and not self._reading.cancelled():
                self._reading.exception()
        self._pcm = bytearray()

    async def _read(self, pcm: bytes) -> _Read:
        if not pcm:
            raise InferenceUnavailable("no audio was heard")
        started = time.perf_counter()
        voiceprint = await services.get(Inference).voiceprint(_FORMAT, pcm)
        self._fields["voiceprint_ms"] = int((time.perf_counter() - started) * 1000)
        household_id = self._device.household_id
        prints, home = await asyncio.gather(services.get(Voices).prints(household_id, voiceprint.model),
                                            services.get(Presence).home(household_id))
        return _Read(voiceprint, prints, home)

    async def _decide(self, read: _Read) -> int | None:
        if read.voiceprint.audio_ms >= self._policy.min_audio_ms:
            enrolled = await services.get(Voices).enrol(self._device.id, read.voiceprint)
            if enrolled is not None:
                self._fields.update(outcome="enrolled", remaining=enrolled.remaining)
                return None
        found = match(read.voiceprint, read.prints, read.home, self._policy)
        self._fields.update(outcome=found.outcome, best=_score(found.best), second=_score(found.second),
                            people=len(read.prints), presence=found.presence)
        return found.person_id if self._policy.decides else None


def _score(value: float | None) -> str | None:
    return None if value is None else f"{value:.2f}"
