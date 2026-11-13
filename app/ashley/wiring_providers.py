"""Which providers the settings turn on: the in-process embedding and voiceprint models, the env's keys for the
keyed ones (`ashley.inference.kinds`), the env's local OpenAI-compatible server (`ashley.inference.compatible`) and the
env's Wyoming address (`ashley.inference.wyoming_kind`).
Called by `ashley.wiring.wire`."""

import os

from .inference import compatible, wyoming_kind
from .inference.fastembed_embedder import FastEmbedder
from .inference.provider import Wired
from .inference.provider_keys import KeyInForce
from .inference.sherpa_voiceprint import SherpaVoiceEmbedder
from .settings import Settings


def env_keys(settings: Settings) -> dict[str, str]:
    """The env's key for each keyed provider, by its kind name; empty when unset."""
    return {"anthropic": settings.anthropic_api_key, "openai": settings.openai_api_key,
            "gemini": settings.gemini_api_key, "elevenlabs": settings.elevenlabs_api_key,
            "claude_cli": settings.claude_code_oauth_token}


def env_compatible(settings: Settings) -> dict[str, KeyInForce]:
    """The env's local OpenAI-compatible server as the key of the connection labelled `local`, its key `none` when
    `LOCAL_LLM_API_KEY` is unset (a server that takes none ignores it); empty when `LOCAL_LLM_URL` is unset."""
    url = settings.local_llm_url.strip()
    if not url:
        return {}
    return {compatible.LOCAL: KeyInForce(compatible.NAME, settings.local_llm_api_key or "none", None,
                                         compatible.KIND.base_url(url) or url, compatible.LOCAL)}


def env_addressed(settings: Settings) -> dict[str, str]:
    """The env's address for each provider reached at an address and no key, by its kind name; empty when unset."""
    return {wyoming_kind.NAME: settings.wyoming_stt_url}


def providers(settings: Settings) -> list[Wired]:
    """The providers no connection turns on: the in-process embedding and voiceprint models."""
    wired: list[Wired] = []
    wired.append(FastEmbedder("fastembed", settings.embed_models_dir))
    if os.path.isfile(settings.voiceprint_model_path):
        wired.append(SherpaVoiceEmbedder("sherpa", settings.voiceprint_model_path))
    return wired
