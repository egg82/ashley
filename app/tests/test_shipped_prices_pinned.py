"""What the shipped routes' models cost for a fixed usage, pinned before the price source changes: each row is the cost
`prices.json` gave on the pin date, so a new source shows every model whose cost moved."""

from datetime import date
from decimal import Decimal

import pytest
from ashley.inference import prices
from ashley.inference.model import Usage

ON = date(2026, 11, 13)
SMALL = Usage(1_000, 500, 200, 100)
LONG = Usage(150_000, 2_000, 30_000, 300_000)
SMALL_NO_WRITE = Usage(1_000, 500, 200, 0)
LONG_NO_WRITE = Usage(250_000, 2_000, 30_000, 0)

PINNED: list[tuple[str, str, Usage, str | None]] = [
    ("anthropic", "claude-opus-5-5", SMALL, "0.01454"),
    ("anthropic", "claude-opus-5-5", LONG, "2.146"),
    ("anthropic", "claude-sonnet-5-5", SMALL, "0.00727"),
    ("anthropic", "claude-sonnet-5-5", LONG, "1.073"),
    ("anthropic", "claude-haiku-5-5", SMALL, "0.0003645"),
    ("anthropic", "claude-haiku-5-5", LONG, "0.269"),
    ("openai", "gpt-6-luna", SMALL, "0.0003645"),
    ("openai", "gpt-6-luna", LONG, "0.1071"),
    ("openai", "gpt-6.1-sol", SMALL, "0.00727"),
    ("openai", "gpt-6.1-sol", LONG, "2.136"),
    ("gemini", "gemini-4-argon", SMALL_NO_WRITE, "0.00702"),
    ("gemini", "gemini-4-argon", LONG_NO_WRITE, "0.523"),
    ("gemini", "gemini-3.8-flash", SMALL_NO_WRITE, "0.00264"),
    ("gemini", "gemini-3.8-flash", LONG_NO_WRITE, "0.19725"),
    ("gemini", "gemini-3.5-flash-lite", SMALL_NO_WRITE, "0.001556"),
    ("gemini", "gemini-3.5-flash-lite", LONG_NO_WRITE, "0.0809"),
    ("gemini_image", "gemini-3.1-flash-lite-image", SMALL_NO_WRITE, "0.0153"),
    ("gemini_image", "gemini-3.1-flash-lite-image", LONG_NO_WRITE, "0.13"),
    ("openai_image", "gpt-image-2.5-flare", Usage(12, 196), "0.00594"),
    ("fastembed", "thenlper/gte-base", Usage(0, 0, characters=40), "0"),
    ("sherpa", "nemo_en_titanet_small", Usage(0, 0, audio_ms=5000), "0"),
    ("openai", "gpt-4o-mini-transcribe", Usage(0, 0, audio_ms=5000), None),
    ("elevenlabs", "eleven_flash_v2_5", Usage(0, 0, characters=50), None),
    ("local", "qwen3-32b", SMALL, None),
]


def cost(provider: str, model: str, usage: Usage) -> Decimal | None:
    return prices.load().cost_usd(provider, model, usage, ON)


@pytest.mark.parametrize(("provider", "model", "usage", "expected"), PINNED,
                         ids=[f"{p}/{m}/{i}" for i, (p, m, _, _) in enumerate(PINNED)])
def test_a_shipped_model_costs_what_was_pinned(provider: str, model: str, usage: Usage, expected: str | None) -> None:
    found = cost(provider, model, usage)
    assert found == (None if expected is None else Decimal(expected))
