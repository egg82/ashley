"""Which providers the settings turn on: one per inference setting that is present. Called by `ashley.wiring.wire`."""

import os

from anthropic import AsyncAnthropic
from openai import AsyncOpenAI

from .inference.fastembed_embedder import FastEmbedder
from .inference.provider import Wired
from .inference.providers import AnthropicProvider, OpenAICompatibleProvider
from .inference.sherpa_voiceprint import SherpaVoiceEmbedder
from .inference.wyoming_stt import WyomingTranscriber
from .settings import Settings


def providers(settings: Settings) -> list[Wired]:
    """One provider per inference setting that is present."""
    wired: list[Wired] = []
    if settings.anthropic_api_key:
        wired.append(AnthropicProvider("anthropic", AsyncAnthropic(api_key=settings.anthropic_api_key, max_retries=0)))
    if settings.openai_api_key:
        wired.append(OpenAICompatibleProvider("openai", AsyncOpenAI(api_key=settings.openai_api_key, max_retries=0)))
    if settings.gemini_api_key:
        wired.append(OpenAICompatibleProvider("gemini", AsyncOpenAI(
            api_key=settings.gemini_api_key, max_retries=0,
            # https://ai.google.dev/gemini-api/docs/openai
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/")))
    if settings.local_llm_url:
        wired.append(OpenAICompatibleProvider("local", AsyncOpenAI(
            api_key=settings.local_llm_api_key or "none", base_url=settings.local_llm_url, max_retries=0)))
    if settings.wyoming_stt_url:
        wired.append(WyomingTranscriber("wyoming", settings.wyoming_stt_url))
    wired.append(FastEmbedder("fastembed", settings.embed_models_dir))
    if os.path.isfile(settings.voiceprint_model_path):
        wired.append(SherpaVoiceEmbedder("sherpa", settings.voiceprint_model_path))
    return wired
