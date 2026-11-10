"""Stand-ins for the voiceprint tests: a scripted `VoiceEmbedder` for the router. Nothing loads a real model."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from typing import get_args

from ashley.inference.model import Route, Task
from ashley.inference.prices import Prices
from ashley.inference.provider import ProviderFailed
from ashley.inference.router import RoutedInference
from ashley.inference.routes import Routes
from ashley.inference.speech import AudioFormat
from ashley.inference.voiceprint import VoiceprintTask
from ashley.inference.voiceprint_provider import VoiceEmbedder
from speech_support import MemoryLedger


@dataclass
class ScriptedVoiceEmbedder(VoiceEmbedder):
    """Answers every utterance with `vector`, or raises `error`; keeps what it was asked."""

    label: str
    vector: tuple[float, ...] = (1.0, 0.0)
    error: ProviderFailed | None = None
    seen: list[tuple[str, int, AudioFormat]] = field(default_factory=list[tuple[str, int, AudioFormat]])

    @property
    def name(self) -> str:
        return self.label

    def check_voiceprint_params(self, params: Mapping[str, object]) -> None:
        return None

    async def voiceprint(self, model: str, params: Mapping[str, object], pcm: bytes, format: AudioFormat,
                         timeout_s: float) -> list[float]:
        self.seen.append((model, len(pcm), format))
        if self.error is not None:
            raise self.error
        return list(self.vector)


def voiceprint_router(*providers: VoiceEmbedder,
                      prices: Prices = Prices({})) -> tuple[RoutedInference, MemoryLedger]:
    text: dict[Task, tuple[Route, ...]] = {t: (Route("none", "m", 1.0),) for t in get_args(Task)}
    task: VoiceprintTask = "voiceprint"
    routes = Routes(text, 300.0, voiceprint={task: tuple(Route(p.name, f"{p.name}-model", 5.0) for p in providers)})
    ledger = MemoryLedger()
    return RoutedInference(routes, providers, ledger, prices, today=lambda: date(2026, 10, 27)), ledger
