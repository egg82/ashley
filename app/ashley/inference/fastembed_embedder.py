"""`FastEmbedder`: embeddings from a model run in this process on the CPU (fastembed over ONNX), with no network.

Route `model` is a fastembed model name (`thenlper/gte-base`), read from `models_dir`, where the image has put it at
build time; a model missing there fails the call `unavailable`, so the router rests the provider instead of retrying
every call. No params. The model for each name is loaded once per process, on first use, inside the call's
`timeout_s`; a load that outlasts it finishes in the background and the next call finds the model loaded. Inference
runs in a worker thread, so the event loop is never held; calls to one model run one at a time."""

import asyncio
import math
import threading
from collections.abc import Mapping, Sequence

from fastembed import TextEmbedding

from .embedding import EmbedRole
from .embed_provider import Embedder
from .provider import ProviderFailed


class FastEmbedder(Embedder):
    def __init__(self, name: str, models_dir: str) -> None:
        self._name = name
        self._models_dir = models_dir
        self._models: dict[str, TextEmbedding] = {}
        self._lock = threading.RLock()

    @property
    def name(self) -> str:
        return self._name

    def check_embed_params(self, params: Mapping[str, object]) -> None:
        if params:
            raise ValueError(f"unknown parameter {sorted(params)[0]!r}")

    async def embed(self, model: str, params: Mapping[str, object], texts: Sequence[str], role: EmbedRole,
                    timeout_s: float) -> list[list[float]]:
        try:
            async with asyncio.timeout(timeout_s):
                return await asyncio.to_thread(self._embed, model, list(texts), role)
        except (TimeoutError, OSError, ValueError, RuntimeError) as e:
            raise ProviderFailed("unavailable", type(e).__name__) from e
        except Exception as e:
            raise ProviderFailed("error", type(e).__name__) from e

    async def warm(self, model: str, params: Mapping[str, object], timeout_s: float) -> None:
        try:
            async with asyncio.timeout(timeout_s):
                await asyncio.to_thread(self._load, model)
        except (TimeoutError, OSError, ValueError, RuntimeError) as e:
            raise ProviderFailed("unavailable", type(e).__name__) from e
        except Exception as e:
            raise ProviderFailed("error", type(e).__name__) from e

    def _load(self, model: str) -> TextEmbedding:
        with self._lock:
            loaded = self._models.get(model)
            if loaded is None:
                loaded = self._models[model] = TextEmbedding(model, cache_dir=self._models_dir, threads=1,
                                                             local_files_only=True)
            return loaded

    def _embed(self, model: str, texts: list[str], role: EmbedRole) -> list[list[float]]:
        with self._lock:
            loaded = self._load(model)
            made = loaded.query_embed(texts) if role == "query" else loaded.passage_embed(texts)
            return [_unit([float(x) for x in vector]) for vector in made]


def _unit(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vector))
    return [x / norm for x in vector] if norm else vector
