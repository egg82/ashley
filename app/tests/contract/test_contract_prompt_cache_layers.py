"""The system prompt in two layers, so a new minute does not rewrite the cache: `persona.system` returns a `SystemPrompt`
(the stable text, then what changes per message), `AnthropicProvider` caches the tools and the stable text and sends
the moment as the last block of the last user turn after the last breakpoint, uncached, and every other provider is sent
the moment as a user message after the history."""

import json
from dataclasses import replace
from datetime import timedelta
from typing import Any

import pytest
from ashley import logs
from ashley.inference.model import Entry, Message, SystemPrompt, ToolCall, ToolCalls, ToolResult, ToolResults, ToolSpec
from ashley.inference.provider import ProviderFailed
from ashley.inference.reply import Reply
from ashley.persona.persona import Context, system
from inference_support import answered, settle
from inference_wire_support import (Answer, anthropic_body, anthropic_provider, openai_body, openai_provider,
                                    system_blocks, text_of)
from test_contract_persona import CONTEXT

LIGHTS = ToolSpec("lights_on", "which lights are on", {"type": "object"}, True)
SWITCH = ToolSpec("switch", "turn something on or off", {"type": "object"})
LATER = replace(CONTEXT, now=CONTEXT.now + timedelta(minutes=1))
MESSAGES = (Message("person", "hello"),)


def sent(prompt_system: SystemPrompt, tools: tuple[ToolSpec, ...] = (LIGHTS, SWITCH)) -> dict[str, Any]:
    provider, stand = anthropic_provider(Answer(body=anthropic_body()))
    answered(settle(provider.complete("claude-test-1", {"max_tokens": 5}, prompt_system, MESSAGES, tools, "auto",
                                      Reply, 9.0)))
    return stand.sent[0]


def layered(context: Context) -> SystemPrompt:
    return system("chat", context)["default"]


def marked(body: dict[str, Any]) -> list[str]:
    """Where the request's breakpoints are, in render order: `tool:<name>` or `system:<index>`."""
    found = [f"tool:{t['name']}" for t in body.get("tools", []) if t.get("cache_control")]
    found += [f"system:{i}" for i, b in enumerate(system_blocks(body["system"])) if b.get("cache_control")]
    for n, turn in enumerate(body["messages"]):
        blocks: list[dict[str, Any]] = turn["content"] if isinstance(turn["content"], list) else []
        found += [f"message:{n}" for b in blocks if b.get("cache_control")]
    return found


def test_the_clock_is_after_the_last_breakpoint() -> None:
    body = sent(layered(CONTEXT))
    assert "# Now" not in text_of(system_blocks(body["system"]))
    blocks = body["messages"][-1]["content"]
    assert "# Now" in blocks[-1]["text"] and not blocks[-1].get("cache_control")
    assert blocks[-2].get("cache_control") and blocks[-2]["text"] == "hello"


def test_the_breakpoints_are_the_last_tool_the_stable_text_and_the_last_turn_and_no_more() -> None:
    body = sent(layered(CONTEXT))
    assert marked(body) == ["tool:switch", "system:0", "message:0"]
    assert body["messages"][0]["content"][-2]["text"] == "hello"
    assert body["tools"][0].get("cache_control") is None


def test_the_cached_part_is_byte_identical_across_two_minutes() -> None:
    first, second = sent(layered(CONTEXT)), sent(layered(LATER))
    assert layered(CONTEXT).moment != layered(LATER).moment, "the control: the minute really changed the text"
    assert json.dumps(first["tools"], sort_keys=True) == json.dumps(second["tools"], sort_keys=True)
    assert first["system"] == second["system"]
    assert first["messages"][0]["content"][:-1] == second["messages"][0]["content"][:-1]
    assert first["messages"][0]["content"][-1] != second["messages"][0]["content"][-1]


def test_what_changes_per_message_is_after_the_breakpoint_too() -> None:
    said = replace(CONTEXT, said_before=("(2 days ago) Casey: zqSAID",))
    plain, more = layered(CONTEXT), layered(said)
    assert plain.stable == more.stable
    assert "zqSAID" in more.moment and "zqSAID" not in more.stable


def test_the_whole_text_is_the_stable_text_then_the_moment() -> None:
    got = layered(CONTEXT)
    assert got.text == got.stable + "\n\n" + got.moment
    body = sent(got)
    assert text_of(system_blocks(body["system"])) == got.stable
    assert body["messages"][0]["content"][-1]["text"].endswith(got.moment)


def test_a_prompt_with_no_moment_is_one_cached_block_and_the_last_tool_is_cached() -> None:
    body = sent(SystemPrompt("You are Ashley."))
    blocks = system_blocks(body["system"])
    assert len(blocks) == 1 and blocks[0]["cache_control"] == {"type": "ephemeral"}
    assert marked(body) == ["tool:switch", "system:0", "message:0"]
    assert len(body["messages"][0]["content"]) == 1, "no moment, no moment block"


def test_with_no_tools_only_the_stable_text_is_a_breakpoint() -> None:
    assert marked(sent(layered(CONTEXT), tools=())) == ["system:0", "message:0"]


def test_another_provider_is_sent_the_stable_text_as_system_and_the_moment_after_the_history() -> None:
    provider, stand = openai_provider(Answer(body=openai_body()))
    got = layered(CONTEXT)
    answered(settle(provider.complete("gpt-test", {"max_completion_tokens": 5}, got, MESSAGES, (), "auto", Reply, 9.0)))
    sent_messages = stand.sent[0]["messages"]
    assert sent_messages[0]["role"] in ("system", "developer") and text_of(sent_messages[0]["content"]) == got.stable
    assert [m["role"] for m in sent_messages[1:]] == ["user", "user"]
    assert sent_messages[1]["content"] == "hello" and text_of(sent_messages[2]["content"]).endswith(got.moment)


def test_two_messages_of_one_conversation_share_every_block_but_the_moment() -> None:
    """The reason the moment is last: what was sent for message one is a prefix of message two."""
    first_turn = (Message("person", "hello"),)
    second_turn = (*first_turn, Message("ashley", "hi"), Message("person", "and now?"))
    bodies: list[dict[str, Any]] = []
    for entries, prompt in ((first_turn, SystemPrompt("s", "minute one")), (second_turn, SystemPrompt("s", "minute two"))):
        provider, stand = anthropic_provider(Answer(body=anthropic_body()))
        answered(settle(provider.complete("claude-test-1", {"max_tokens": 5}, prompt, entries, (), "auto", Reply, 9.0)))
        bodies.append(stand.sent[0])
    one, two = bodies
    assert one["system"] == two["system"]
    assert one["messages"][0]["content"][0]["text"] == two["messages"][0]["content"] == "hello"
    assert "minute one" not in json.dumps(two) and "minute two" in json.dumps(two)


def test_a_prompt_without_a_moment_is_one_cached_block() -> None:
    blocks = system_blocks(sent(SystemPrompt("only stable"))["system"])
    assert [b["text"] for b in blocks] == ["only stable"] and blocks[0].get("cache_control")


def test_a_prompt_needs_a_stable_part() -> None:
    with pytest.raises(ValueError):
        SystemPrompt("  ", "moment")


def test_a_prompt_cannot_be_flattened_to_text_without_saying_so() -> None:
    got = layered(CONTEXT)
    assert not isinstance(got, str), "a str would let a concatenation or f-string drop the layers unseen"
    assert isinstance(f"{got.stable}\n\n{got.moment}", str) and got.text == f"{got.stable}\n\n{got.moment}"


def test_a_provider_refuses_a_plain_string_for_the_system_prompt() -> None:
    flat: Any = layered(CONTEXT).text
    provider, stand = anthropic_provider(Answer(body=anthropic_body()))
    with pytest.raises(ProviderFailed):
        settle(provider.complete("claude-test-1", {"max_tokens": 5}, flat, MESSAGES, (), "auto", Reply, 9.0))
    assert stand.sent == []


def test_the_tail_breakpoint_is_on_the_last_block_of_the_last_turn_of_a_tool_round() -> None:
    entries = (Message("person", "lights?"),
               ToolCalls((ToolCall("t1", "lights_on", {}), ToolCall("t2", "switch", {}))),
               ToolResults((ToolResult("t1", "on", False), ToolResult("t2", "done", False))))
    provider, stand = anthropic_provider(Answer(body=anthropic_body()))
    answered(settle(provider.complete("claude-test-1", {"max_tokens": 5}, layered(CONTEXT), entries, (LIGHTS, SWITCH),
                                      "auto", Reply, 9.0)))
    body = stand.sent[0]
    assert marked(body) == ["tool:switch", "system:0", "message:2"]
    assert [b.get("cache_control") for b in body["messages"][2]["content"]] == [None, {"type": "ephemeral"}, None]
    assert "# Now" in body["messages"][2]["content"][-1]["text"]
    assert body["messages"][0]["content"] == "lights?"


def test_each_call_logs_a_hash_per_cached_layer_that_moves_with_that_layer_only(capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()

    def hashes(system_prompt: SystemPrompt, entries: tuple[Entry, ...]) -> dict[str, str]:
        capsys.readouterr()
        provider, _ = anthropic_provider(Answer(body=anthropic_body()))
        answered(settle(provider.complete("claude-test-1", {"max_tokens": 5}, system_prompt, entries,
                                          (LIGHTS, SWITCH), "auto", Reply, 9.0)))
        line = next(ln for ln in capsys.readouterr().out.splitlines() if "inference.cache_layers" in ln)
        assert "hello" not in line and "only stable" not in line
        return dict(p.split("=", 1) for p in line.split() if p.split("=", 1)[0] in ("tools", "stable", "tail"))
    base = hashes(SystemPrompt("only stable", "m1"), MESSAGES)
    assert all(len(v) == 12 for v in base.values()) and len(base) == 3
    assert hashes(SystemPrompt("only stable", "m2"), MESSAGES) == base, "the moment is not a cached layer"
    other = hashes(SystemPrompt("other stable", "m1"), MESSAGES)
    assert other["stable"] != base["stable"] and other["tools"] == base["tools"] and other["tail"] == base["tail"]
    longer = hashes(SystemPrompt("only stable", "m1"), (Message("person", "hello!"),))
    assert longer["tail"] != base["tail"] and longer["stable"] == base["stable"]
