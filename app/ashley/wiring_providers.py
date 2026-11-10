"""Which providers the settings turn on: one per keyless inference setting that is present, and the env's keys for the
keyed ones (`ashley.inference.kinds`). Called by `ashley.wiring.wire`."""

import os

from openai import AsyncOpenAI

from .inference.fastembed_embedder import FastEmbedder
from .inference.provider import Wired
from .inference.providers import OpenAICompatibleProvider
from .inference.sherpa_voiceprint import SherpaVoiceEmbedder
from .inference.wyoming_stt import WyomingTranscriber
from .settings import Settings


def env_keys(settings: Settings) -> dict[str, str]:
    """The env's key for each keyed provider, by its kind name; empty when unset."""
    return {"anthropic": settings.anthropic_api_key, "openai": settings.openai_api_key,
            "gemini": settings.gemini_api_key, "elevenlabs": settings.elevenlabs_api_key}


def providers(settings: Settings) -> list[Wired]:
    """One provider per keyless inference setting that is present: a local server, Wyoming speech-to-text, and the
    in-process embedding and voiceprint models."""
    wired: list[Wired] = []
    if settings.local_llm_url:
        wired.append(OpenAICompatibleProvider("local", AsyncOpenAI(
            api_key=settings.local_llm_api_key or "none", base_url=settings.local_llm_url, max_retries=0)))
    if settings.wyoming_stt_url:
        wired.append(WyomingTranscriber("wyoming", settings.wyoming_stt_url))
    wired.append(FastEmbedder("fastembed", settings.embed_models_dir))
    if os.path.isfile(settings.voiceprint_model_path):
        wired.append(SherpaVoiceEmbedder("sherpa", settings.voiceprint_model_path))
    return wired
