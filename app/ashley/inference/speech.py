"""What goes into and comes out of a speech call, as values: audio as it is heard, the words in it, and her voice."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal

SpeechTask = Literal["transcribe", "speak"]
"""What a speech call is for, which picks its routes in `routes.json` beside the text tasks."""


@dataclass(frozen=True)
class AudioFormat:
    """Raw little-endian PCM: `rate` samples per second, `width` bytes per sample, `channels` interleaved. Raises
    ValueError on construction when any is not positive."""

    rate: int = 16000
    width: int = 2
    channels: int = 1

    def __post_init__(self) -> None:
        if self.rate <= 0 or self.width <= 0 or self.channels <= 0:
            raise ValueError("audio rate, width and channels must be positive")

    @property
    def frame_bytes(self) -> int:
        return self.width * self.channels

    def duration_ms(self, pcm_bytes: int) -> int:
        return pcm_bytes * 1000 // (self.rate * self.frame_bytes)


@dataclass(frozen=True)
class Heard:
    """One utterance as it arrives: PCM in `format`, chunk by chunk, ending when the speaker stopped (the caller
    decides that). Chunks may be any size; together they are a whole number of frames. `chunks` is read at most once,
    by `Inference.transcribe`, which keeps what it read so another route can be given the same utterance. `language`
    is the ISO 639-1 code of the language spoken when the caller knows it (a household's), which overrides any language
    a route's params name; None leaves each route to its own."""

    format: AudioFormat
    chunks: AsyncIterator[bytes]
    language: str | None = None


@dataclass(frozen=True)
class Transcript:
    """The words heard, in real spellings, stripped; empty when nothing was said. `provider` and `model` name the
    route that answered (`Route.provider`, `Route.model`)."""

    text: str
    provider: str
    model: str


@dataclass(frozen=True)
class Speech:
    """Her voice saying one text: `media_type` (`audio/mpeg`, `audio/wav`, ...) and the bytes as they arrive, so a
    player can start before synthesis ends. `chunks` is read at most once. `provider` and `model` name the route that
    started answering (`Route.provider`, `Route.model`)."""

    media_type: str
    chunks: AsyncIterator[bytes]
    provider: str
    model: str
