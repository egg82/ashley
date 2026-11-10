"""`SherpaVoiceEmbedder`: voiceprints from a speaker-embedding model run in this process on the CPU (sherpa-onnx), with
no network.

The model is the one file at `model_path`, where the image has put it at build time; the route's `model` only labels the
prints. A file missing there fails the call `unavailable`, so the router rests the provider instead of retrying every
call. No params. Takes only 16 kHz mono 16-bit audio; any other format fails the call `error`. The model is loaded once
per process, on first use or on `warm`, inside the call's `timeout_s`; a load that outlasts it finishes in the
background and the next call finds the model loaded. Extraction runs in a worker thread, so the event loop is never
held; calls run one at a time."""

import asyncio
import math
import os
import struct
import threading
from collections.abc import Mapping

import sherpa_onnx

from .provider import ProviderFailed
from .speech import AudioFormat
from .voiceprint_provider import VoiceEmbedder

RATE = 16000
SUPPORTED = AudioFormat(rate=RATE, width=2, channels=1)


class SherpaVoiceEmbedder(VoiceEmbedder):
    def __init__(self, name: str, model_path: str) -> None:
        self._name = name
        self._model_path = model_path
        self._extractor: sherpa_onnx.SpeakerEmbeddingExtractor | None = None
        self._lock = threading.RLock()

    @property
    def name(self) -> str:
        return self._name

    def check_voiceprint_params(self, params: Mapping[str, object]) -> None:
        if params:
            raise ValueError(f"unknown parameter {sorted(params)[0]!r}")

    async def voiceprint(self, model: str, params: Mapping[str, object], pcm: bytes, format: AudioFormat,
                         timeout_s: float) -> list[float]:
        if format != SUPPORTED:
            raise ProviderFailed("error", "UnsupportedFormat")
        try:
            async with asyncio.timeout(timeout_s):
                return await asyncio.to_thread(self._extract, pcm)
        except ProviderFailed:
            raise
        except (TimeoutError, OSError, ValueError, RuntimeError) as e:
            raise ProviderFailed("unavailable", type(e).__name__) from e
        except Exception as e:
            raise ProviderFailed("error", type(e).__name__) from e

    async def warm(self, model: str, params: Mapping[str, object], timeout_s: float) -> None:
        try:
            async with asyncio.timeout(timeout_s):
                await asyncio.to_thread(self._load)
        except (TimeoutError, OSError, ValueError, RuntimeError) as e:
            raise ProviderFailed("unavailable", type(e).__name__) from e
        except Exception as e:
            raise ProviderFailed("error", type(e).__name__) from e

    def _load(self) -> sherpa_onnx.SpeakerEmbeddingExtractor:
        with self._lock:
            if self._extractor is None:
                if not os.path.isfile(self._model_path):
                    raise FileNotFoundError(self._model_path)
                config = sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=self._model_path, num_threads=1)
                self._extractor = sherpa_onnx.SpeakerEmbeddingExtractor(config)
            return self._extractor

    def _extract(self, pcm: bytes) -> list[float]:
        with self._lock:
            extractor = self._load()
            stream = extractor.create_stream()
            stream.accept_waveform(RATE, [s / 32768 for s in struct.unpack(f"<{len(pcm) // 2}h", pcm)])
            stream.input_finished()
            if not extractor.is_ready(stream):
                raise ProviderFailed("invalid_output", "TooShort")
            return _unit([float(x) for x in extractor.compute(stream)])


def _unit(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vector))
    if not norm or not math.isfinite(norm):
        raise ProviderFailed("invalid_output", "NoVector")
    return [x / norm for x in vector]
