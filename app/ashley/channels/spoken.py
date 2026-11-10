"""One utterance spoken into a page (web chat or the kiosk), as the browser recorded it: a WAV of 16 kHz 16-bit mono
PCM, the format the voice pipeline hears, so no codec runs on either side. Its words come from
`Inference.transcribe`; the audio lives in memory for that one call and is never stored. The longest utterance, the
loudness the page counts as speech, and how long her spoken answer to it can be fetched are data, `spoken.json`."""

import io
import json
import wave
from collections.abc import AsyncIterator
from dataclasses import dataclass
from importlib import resources
from typing import Any

from .. import services
from ..inference.inference import Inference, InferenceUnavailable
from ..inference.speech import AudioFormat, Heard

FORMAT = AudioFormat()
WAV_HEADER_BYTES = 44
"""A plain PCM WAV's header: what the page writes, and all the room a body has beside its samples."""


@dataclass(frozen=True)
class Caps:
    """An utterance lasts at most `max_ms` (>= 1000), so its WAV is at most `max_bytes`. `quiet_rms` (0 to 1,
    exclusive) is the RMS of the microphone's samples, in -1..1, at which the page hears speech. Her answer aloud to it
    can be fetched for `voice_s` seconds (>= 1) after her turn is stored."""

    max_ms: int
    quiet_rms: float
    voice_s: int

    @property
    def max_bytes(self) -> int:
        return WAV_HEADER_BYTES + self.max_ms * FORMAT.rate // 1000 * FORMAT.frame_bytes


class Unsupported(Exception):
    """Not a WAV of 16 kHz 16-bit mono PCM."""


class TooLong(Exception):
    """Longer than `Caps.max_ms`."""


class SpokenUnavailable(Exception):
    """No transcription route answered."""


def load() -> Caps:
    """The caps shipped in `spoken.json` beside this module. Raises ValueError when it is malformed."""
    return parse(json.loads(resources.files("ashley.channels").joinpath("spoken.json").read_text()))


def parse(data: object) -> Caps:
    """Caps from JSON already parsed: `{"max_ms": n, "quiet_rms": x, "voice_s": m}` with n an integer >= 1000, x a number
    strictly between 0 and 1 and m an integer >= 1, and nothing else. Raises ValueError otherwise."""
    raw: Any = data
    fields = dict[str, object](raw) if hasattr(raw, "keys") else {}
    if set(fields) != {"max_ms", "quiet_rms", "voice_s"}:
        raise ValueError("spoken caps is an object with exactly max_ms, quiet_rms and voice_s")
    most, quiet, voice = fields["max_ms"], fields["quiet_rms"], fields["voice_s"]
    if type(most) is not int or most < 1000:
        raise ValueError("spoken caps max_ms: expected an integer >= 1000")
    if isinstance(quiet, bool) or not isinstance(quiet, int | float) or not 0 < quiet < 1:
        raise ValueError("spoken caps quiet_rms: expected a number between 0 and 1")
    if type(voice) is not int or voice < 1:
        raise ValueError("spoken caps voice_s: expected an integer >= 1")
    return Caps(most, float(quiet), voice)


def pcm_of(wav: bytes, caps: Caps) -> bytes:
    """The samples of `wav`. Raises Unsupported for anything but 16 kHz 16-bit mono PCM WAV, TooLong past the cap."""
    try:
        with wave.open(io.BytesIO(wav), "rb") as read:
            shape = (read.getframerate(), read.getsampwidth(), read.getnchannels())
            frames = read.getnframes()
            pcm = read.readframes(frames)
    except (wave.Error, EOFError) as e:
        raise Unsupported() from e
    if shape != (FORMAT.rate, FORMAT.width, FORMAT.channels) or len(pcm) != frames * FORMAT.frame_bytes:
        raise Unsupported()
    if FORMAT.duration_ms(len(pcm)) > caps.max_ms:
        raise TooLong()
    return pcm


async def _once(pcm: bytes) -> AsyncIterator[bytes]:
    yield pcm


async def words_in(pcm: bytes) -> str:
    """What was said in `pcm` (16 kHz 16-bit mono), empty when nothing was; no call is made for no audio. Raises
    SpokenUnavailable."""
    if not pcm:
        return ""
    try:
        return (await services.get(Inference).transcribe("transcribe", Heard(FORMAT, _once(pcm)))).text
    except InferenceUnavailable as e:
        raise SpokenUnavailable() from e
