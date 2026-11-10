"""What goes into and comes out of a voiceprint call, as values."""

from dataclasses import dataclass
from typing import Literal

VoiceprintTask = Literal["voiceprint"]
"""What a voiceprint call is for, which picks its routes in `routes.json` beside the other tasks."""


@dataclass(frozen=True)
class Voiceprint:
    """How the voice in one utterance sounds: a unit-length `vector`, made by `model` (the answering route's
    `Route.model`) from `audio_ms` of audio. Prints from different models are not comparable."""

    vector: tuple[float, ...]
    model: str
    audio_ms: int
