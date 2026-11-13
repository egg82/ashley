"""Stand-ins for the embedding tests: a scripted `Embedder` for the router, and an `Inference` whose embeddings are
a bag of concepts, so two texts are near exactly when the test says they share one. Nothing loads a real model."""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import get_args

from ashley.inference.embed_provider import Embedder
from ashley.inference.embedding import EmbedRole, Embedded, EmbedTask
from ashley.inference.inference import InferenceUnavailable, NullInference
from ashley.inference.model import Route, Task
from ashley.inference.catalogue import ModelCatalogue
from catalogue_support import NONE
from ashley.inference.provider import ProviderFailed
from ashley.inference.router import RoutedInference
from ashley.inference.routes import Routes
from speech_support import MemoryLedger

DIMENSIONS = 768


def concept_vector(text: str, concepts: Mapping[str, int]) -> tuple[float, ...]:
    """A unit vector with weight on the dimension of each concept word `text` contains, and a little on the last."""
    values = [0.0] * DIMENSIONS
    values[-1] = 0.1
    for word, dimension in concepts.items():
        if word in text.lower():
            values[dimension] += 1.0
    norm = math.sqrt(sum(x * x for x in values))
    return tuple(x / norm for x in values)


class ConceptInference(NullInference):
    """Embeds by `concepts` (word -> dimension) as `model`; raises InferenceUnavailable while `down`. Records the role of
    each call."""

    def __init__(self, concepts: Mapping[str, int], model: str = "fake-1") -> None:
        self.concepts = concepts
        self.model = model
        self.down = False
        self.roles: list[EmbedRole] = []

    async def embed(self, texts: Sequence[str], role: EmbedRole, *, conversation_id: int | None = None) -> Embedded:
        if self.down:
            raise InferenceUnavailable("down")
        self.roles.append(role)
        return Embedded(tuple(concept_vector(t, self.concepts) for t in texts), self.model)


@dataclass
class ScriptedEmbedder(Embedder):
    """Answers every text with `vector`, or raises `error`; keeps what it was asked."""

    label: str
    vector: tuple[float, ...] = (1.0, 0.0)
    error: ProviderFailed | None = None
    seen: list[tuple[str, tuple[str, ...], EmbedRole]] = field(default_factory=list[tuple[str, tuple[str, ...], EmbedRole]])

    @property
    def name(self) -> str:
        return self.label

    def check_embed_params(self, params: Mapping[str, object]) -> None:
        return None

    async def embed(self, model: str, params: Mapping[str, object], texts: Sequence[str], role: EmbedRole,
                    timeout_s: float) -> list[list[float]]:
        self.seen.append((model, tuple(texts), role))
        if self.error is not None:
            raise self.error
        return [list(self.vector) for _ in texts]


def embed_router(*providers: Embedder, prices: ModelCatalogue = NONE) -> tuple[RoutedInference, MemoryLedger]:
    text: dict[Task, tuple[Route, ...]] = {t: (Route("none", "m", 1.0),) for t in get_args(Task)}
    task: EmbedTask = "embed"
    routes = Routes(text, 300.0, embed={task: tuple(Route(p.name, f"{p.name}-model", 5.0) for p in providers)})
    ledger = MemoryLedger()
    return RoutedInference(routes, providers, ledger, prices), ledger
