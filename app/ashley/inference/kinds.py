"""The model providers whose key a person pastes, as connection kinds of the `inference` port and what each key turns
on (`ashley.inference.keyed.KeyedProvider`). Each kind is the deployment's (`ConnectionKind.deployment`), held by the
household, one per provider, at the provider's one API address, and checked with the key by one read
(`key_check.answered`): the models list of Anthropic, OpenAI and Gemini, and ElevenLabs' subscription, the read the
Usage room's quota makes. The Claude subscription's OAuth token is checked by one short call through the CLI it is
used with (`claude_cli.check`)."""

from collections.abc import Awaitable, Callable
from dataclasses import replace

import httpx2
from anthropic import AsyncAnthropic
from openai import AsyncOpenAI

from ..connections.kinds import Check, ConnectionKind, Refusal
from . import claude_cli
from .elevenlabs_quota import ElevenLabsQuota
from .elevenlabs_tts import ElevenLabsSpeaker
from .gemini_image import GeminiImageMaker
from .key_check import answered
from .keyed import Built, KeyedProvider
from .openai_image import OpenAIImageMaker
from .providers import AnthropicProvider, OpenAICompatibleProvider, OpenAIResponsesProvider

ANTHROPIC_API = "https://api.anthropic.com"
OPENAI_API = "https://api.openai.com"
GEMINI_API = "https://generativelanguage.googleapis.com"
GEMINI_OPENAI = GEMINI_API + "/v1beta/openai/"
"""Gemini's OpenAI-compatible endpoint, which chat is sent to: https://ai.google.dev/gemini-api/docs/openai"""
ELEVENLABS_API = "https://api.elevenlabs.io"


def _check(path: str, headers: Callable[[str], dict[str, str]]) -> Check:
    async def check(base: str, key: str, person_id: int) -> Refusal | None:
        async with httpx2.AsyncClient() as http:
            return await answered(http, base + path, headers(key))
    return check


def _kind(name: str, title: str, address: str, check: Check, where: str) -> ConnectionKind:
    return ConnectionKind(
        name=name, title=title, what="a model provider",
        blurb=f"The deployment’s {title} API key. Every household here is answered with it, and its calls are billed "
              f"to it.",
        connected=f"Connected. Her calls to {title} use this key from now on.",
        removed=f"Removed. She calls {title} only if the deployment’s own setup has a key for it.",
        holders=frozenset({"household"}), schemes=frozenset({"https"}), address_placeholder="",
        secret_field="api_key", secret_label=f"API key, from {where}", secret_noun="key", check=check,
        ports=frozenset({"inference"}), fixed_address=address, deployment=True,
        refusals={"bad_url": f"{title} is reached at its own address",
                  "key_refused": f"{title} turned that key away; make one in {where} and paste it here",
                  "unreachable": f"{title} did not answer in time; try again shortly",
                  "wrong_service": f"what answered is not {title}’s API"})


def _closing(*closers: Callable[[], Awaitable[None]]) -> Callable[[], Awaitable[None]]:
    async def close() -> None:
        for closer in closers:
            await closer()
    return close


def _anthropic(key: str) -> Built:
    client = AsyncAnthropic(api_key=key, max_retries=0)
    return Built((AnthropicProvider("anthropic", client),), {}, _closing(client.close))


def _openai(key: str) -> Built:
    chat = AsyncOpenAI(api_key=key, max_retries=0)
    images = httpx2.AsyncClient(base_url=OPENAI_API, headers={"Authorization": f"Bearer {key}"})
    return Built((OpenAIResponsesProvider("openai", chat), OpenAIImageMaker("openai_image", images)), {},
                 _closing(chat.close, images.aclose))


def _gemini(key: str) -> Built:
    chat = AsyncOpenAI(api_key=key, max_retries=0, base_url=GEMINI_OPENAI)
    images = httpx2.AsyncClient(base_url=GEMINI_API, headers={"x-goog-api-key": key})
    return Built((OpenAICompatibleProvider("gemini", chat), GeminiImageMaker("gemini_image", images)), {},
                 _closing(chat.close, images.aclose))


def _elevenlabs(key: str) -> Built:
    client = httpx2.AsyncClient(base_url=ELEVENLABS_API, headers={"xi-api-key": key},
                                limits=httpx2.Limits(keepalive_expiry=30))
    return Built((ElevenLabsSpeaker("elevenlabs", client),), {"elevenlabs": ElevenLabsQuota(client)},
                 _closing(client.aclose))


def _claude_cli(token: str) -> Built:
    return Built((claude_cli.ClaudeCliProvider(claude_cli.NAME, token),), {}, _closing())


ANTHROPIC = KeyedProvider(
    _kind("anthropic", "Anthropic", ANTHROPIC_API,
          _check("/v1/models", lambda k: {"x-api-key": k, "anthropic-version": "2023-06-01"}), "the Claude Console"),
    frozenset({"anthropic"}), _anthropic)
OPENAI = KeyedProvider(
    _kind("openai", "OpenAI", OPENAI_API, _check("/v1/models", lambda k: {"Authorization": f"Bearer {k}"}),
          "the OpenAI platform"),
    frozenset({"openai", "openai_image"}), _openai)
GEMINI = KeyedProvider(
    _kind("gemini", "Gemini", GEMINI_API, _check("/v1beta/models", lambda k: {"x-goog-api-key": k}),
          "Google AI Studio"),
    frozenset({"gemini", "gemini_image"}), _gemini)
ELEVENLABS = KeyedProvider(
    _kind("elevenlabs", "ElevenLabs", ELEVENLABS_API, _check("/v1/user/subscription", lambda k: {"xi-api-key": k}),
          "your ElevenLabs profile"),
    frozenset({"elevenlabs"}), _elevenlabs)
CLAUDE_CLI = KeyedProvider(
    replace(
        _kind(claude_cli.NAME, "Claude subscription", ANTHROPIC_API, claude_cli.check, "claude setup-token"),
        blurb="The deployment’s Claude subscription, reached through the Claude Code CLI with the token "
              "“claude setup-token” prints. Routes that offer no tools may name it; its calls use the subscription’s "
              "allowance, not API credit.",
        connected="Connected. Routes that name the Claude subscription use this token from now on.",
        removed="Removed. She calls the Claude subscription only if the deployment’s own setup has a token for it.",
        secret_field="token", secret_label="OAuth token, from “claude setup-token”", secret_noun="token",
        refusals={"bad_url": "the Claude subscription is reached at its own address",
                  "key_refused": "Claude turned that token away; run “claude setup-token” again and paste the new one",
                  "unreachable": "the Claude CLI did not answer in time; try again shortly",
                  "wrong_service": "what answered is not Claude"}),
    frozenset({claude_cli.NAME}), _claude_cli)

KEYED: tuple[KeyedProvider, ...] = (ANTHROPIC, OPENAI, GEMINI, ELEVENLABS, CLAUDE_CLI)
"""Every keyed provider, in the order the connections room shows them."""
