"""`Provider.prime` and `AnthropicProvider.prime`: the base provider has no prompt cache and sends nothing; Anthropic's
is one token asked after a one-character message with the tools, system prompt and `output_config` a `complete` with the
same arguments sends, so the breakpoints on the last tool and the stable system block are written, with none on the
message; it returns what the request was billed and fails as `complete` does."""

import asyncio
from typing import Any

import pytest
from ashley.inference.model import Message, SystemPrompt, ToolSpec, Usage
from ashley.inference.provider import ProviderFailed
from ashley.inference.reply import Reply
from inference_support import FakeProvider, answered, settle
from inference_wire_support import (STATUS_ERROR, STATUS_UNAVAILABLE, Answer, anthropic_body, anthropic_error,
                                    anthropic_provider, system_blocks)

LIGHTS = ToolSpec("lights_on", "which lights are on", {"type": "object"}, True)
SWITCH = ToolSpec("switch", "turn something on or off", {"type": "object"})
SYSTEM = SystemPrompt("You are Ashley.", "zqMOMENT the clock says noon")
PARAMS: dict[str, object] = {"max_tokens": 777, "effort": "high"}
MODEL = "claude-test-1"
OK = Answer(body=anthropic_body())


def prime_body(tools: tuple[ToolSpec, ...] = (LIGHTS, SWITCH), system: SystemPrompt = SYSTEM) -> dict[str, Any]:
    provider, stand = anthropic_provider(OK)
    assert settle(provider.prime(MODEL, PARAMS, system, tools, Reply, 9.0)) is not None
    assert len(stand.requests) == 1
    return stand.sent[0]


def complete_body(tools: tuple[ToolSpec, ...] = (LIGHTS, SWITCH), system: SystemPrompt = SYSTEM) -> dict[str, Any]:
    provider, stand = anthropic_provider(OK)
    answered(settle(provider.complete(MODEL, PARAMS, system, (Message("person", "hello"),), tools, "auto", Reply, 9.0)))
    return stand.sent[0]


def marked(body: dict[str, Any]) -> list[str]:
    found = [f"tool:{t['name']}" for t in body.get("tools", []) if t.get("cache_control")]
    found += [f"system:{i}" for i, b in enumerate(system_blocks(body["system"])) if b.get("cache_control")]
    for n, turn in enumerate(body["messages"]):
        blocks: list[dict[str, Any]] = turn["content"] if isinstance(turn["content"], list) else []
        found += [f"message:{n}" for b in blocks if b.get("cache_control")]
    return found


def test_the_base_provider_has_no_prompt_cache_and_answers_none() -> None:
    fake = FakeProvider("alpha")
    assert settle(fake.prime("m1", {}, SYSTEM, (LIGHTS,), Reply, 9.0)) is None and not fake.asked


def test_a_prime_asks_for_one_token_after_one_short_user_message_with_no_breakpoint() -> None:
    body = prime_body()
    assert body["max_tokens"] == 1 and body["model"] == MODEL
    assert [m["role"] for m in body["messages"]] == ["user"]
    content = body["messages"][0]["content"]
    blocks: list[dict[str, Any]] = [{"type": "text", "text": content}] if isinstance(content, str) else content
    assert len(blocks) == 1 and len(blocks[0]["text"]) == 1 and not blocks[0].get("cache_control")


def test_a_prime_writes_the_breakpoints_on_the_last_tool_and_the_stable_system_block_only() -> None:
    body = prime_body()
    assert marked(body) == ["tool:switch", "system:0"]
    assert marked(complete_body()) == ["tool:switch", "system:0", "message:0"], "the control: complete's are these plus the turn"


def test_the_moment_is_not_in_the_primed_system_prompt() -> None:
    assert "zqMOMENT" not in str(prime_body())


def test_the_prefix_is_the_one_a_complete_with_the_same_arguments_sends() -> None:
    primed, completed = prime_body(), complete_body()
    for key in ("tools", "system", "output_config"):
        assert primed[key] == completed[key], key
    assert primed["output_config"].get("format") and primed["output_config"]["effort"] == "high"
    assert primed["max_tokens"] != completed["max_tokens"], "the control: the two bodies do differ where they should"


def test_a_prime_with_no_tools_sends_none_and_marks_only_the_system() -> None:
    body = prime_body(tools=())
    assert not body.get("tools") and marked(body) == ["system:0"]
    assert body["system"] == complete_body(tools=())["system"]


def test_a_prime_returns_what_the_request_was_billed() -> None:
    provider, _ = anthropic_provider(Answer(body=anthropic_body(input_tokens=5, output_tokens=1, cache_read=0,
                                                                 cache_write=600)))
    assert settle(provider.prime(MODEL, PARAMS, SYSTEM, (LIGHTS,), Reply, 9.0)) == Usage(
        input_tokens=5, output_tokens=1, cache_read_tokens=0, cache_write_tokens=600)


def test_the_timeout_is_the_one_given() -> None:
    provider, stand = anthropic_provider(OK)
    settle(provider.prime(MODEL, PARAMS, SYSTEM, (LIGHTS,), Reply, 3.5))
    assert stand.read_timeout == 3.5


@pytest.mark.parametrize("status", STATUS_UNAVAILABLE)
def test_a_status_that_says_the_provider_cannot_serve_fails_unavailable(status: int) -> None:
    provider, _ = anthropic_provider(anthropic_error(status))
    with pytest.raises(ProviderFailed) as caught:
        settle(provider.prime(MODEL, PARAMS, SYSTEM, (LIGHTS,), Reply, 9.0))
    assert caught.value.failure == "unavailable"


@pytest.mark.parametrize("status", STATUS_ERROR)
def test_a_request_the_provider_rejects_fails_error(status: int) -> None:
    provider, _ = anthropic_provider(anthropic_error(status))
    with pytest.raises(ProviderFailed) as caught:
        settle(provider.prime(MODEL, PARAMS, SYSTEM, (LIGHTS,), Reply, 9.0))
    assert caught.value.failure == "error"


def test_a_timeout_fails_unavailable() -> None:
    provider, _ = anthropic_provider(Answer(raises="timeout"))
    with pytest.raises(ProviderFailed) as caught:
        asyncio.run(provider.prime(MODEL, PARAMS, SYSTEM, (LIGHTS,), Reply, 9.0))
    assert caught.value.failure == "unavailable"
