"""Which providers the settings turn on: one per keyless inference setting that is present, the env's keys for the
keyed ones (`ashley.inference.kinds`) and the env's local OpenAI-compatible server (`ashley.inference.compatible`).
Called by `ashley.wiring.wire`."""

import os

from .inference import compatible
from .inference.fastembed_embedder import FastEmbedder
from .inference.provider import Wired
from .inference.provider_keys import KeyInForce
from .inference.sherpa_voiceprint import SherpaVoiceEmbedder
from .inference.wyoming_stt import WyomingTranscriber
from .settings import Settings


def env_keys(settings: Settings) -> dict[str, str]:
    """The env's key for each keyed provider, by its kind name; empty when unset."""
    return {"anthropic": settings.anthropic_api_key, "openai": settings.openai_api_key,
            "gemini": settings.gemini_api_key, "elevenlabs": settings.elevenlabs_api_key}


def env_compatible(settings: Settings) -> dict[str, KeyInForce]:
    """The env's local OpenAI-compatible server as the key of the connection labelled `local`, its key `none` when
    `LOCAL_LLM_API_KEY` is unset (a server that takes none ignores it); empty when `LOCAL_LLM_URL` is unset."""
    url = settings.local_llm_url.strip()
    if not url:
        return {}
    return {compatible.LOCAL: KeyInForce(compatible.NAME, settings.local_llm_api_key or "none", None,
                                         compatible.KIND.base_url(url) or url, compatible.LOCAL)}


def providers(settings: Settings) -> list[Wired]:
    """One provider per keyless inference setting that is present: Wyoming speech-to-text, and the in-process embedding
    and voiceprint models."""
    wired: list[Wired] = []
    if settings.wyoming_stt_url:
        wired.append(WyomingTranscriber("wyoming", settings.wyoming_stt_url))
    wired.append(FastEmbedder("fastembed", settings.embed_models_dir))
    if os.path.isfile(settings.voiceprint_model_path):
        wired.append(SherpaVoiceEmbedder("sherpa", settings.voiceprint_model_path))
    return wired
