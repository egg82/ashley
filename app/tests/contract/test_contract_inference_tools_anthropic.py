"""`AnthropicProvider` with tools: the request carries `tools` and `tool_choice` in the Messages API format, history
entries are translated in order as `tool_use` and `tool_result` blocks, and a tool-use response becomes `ToolUse`."""

from typing import Any

import pytest
from ashley.inference.model import Message, Prompt, ToolCall, ToolCalls, ToolResult, ToolResults
from ashley.inference.provider import Completion, ProviderFailed, ToolUse
from inference_tools_support import TOOLS, call, one_round, results_for, tool_prompt
from inference_tools_wire_support import ANTHROPIC_USAGE, ask, anthropic_items, anthropic_tool_body
from inference_wire_support import Answer, anthropic_body, anthropic_provider

ASK = Message("person", "turn it on")
USE = Answer(body=anthropic_tool_body(("toolu_1", "lights_on", {"q": "hall"})))


def sent(prompt_: Prompt, answer: Answer = Answer(body=anthropic_body())) -> dict[str, Any]:
    provider, stand = anthropic_provider(answer)
    ask(provider, prompt_)
    return stand.sent[0]


def test_the_tools_are_sent_with_name_description_and_input_schema() -> None:
    body = sent(tool_prompt(ASK))
    assert [(t["name"], t["description"], t["input_schema"]) for t in body["tools"]] == [
        (t.name, t.description, dict(t.parameters)) for t in TOOLS]


def test_tool_choice_auto_is_sent_as_the_auto_type() -> None:
    assert sent(tool_prompt(ASK))["tool_choice"]["type"] == "auto"


def test_tool_choice_none_is_sent_as_the_none_type_with_the_tools_still_defined() -> None:
    body = sent(one_round(tool_choice="none"))
    assert body["tool_choice"]["type"] == "none"
    assert [t["name"] for t in body["tools"]] == [t.name for t in TOOLS]


def test_no_tools_means_no_tools_and_no_tool_choice_in_the_request() -> None:
    body = sent(tool_prompt(ASK, tools=()))
    assert not body.get("tools") and body.get("tool_choice") is None


def test_history_is_translated_in_order_with_ids_names_arguments_and_results() -> None:
    calls = (call("a1", "lights_on", q="hall"), call("a2", "weather", city="Oslo"))
    prompt = tool_prompt(ASK, ToolCalls(calls),
                         ToolResults((ToolResult("a1", "lit"), ToolResult("a2", '{"t": 4}', True))),
                         Message("ashley", "done"), Message("person", "thanks"))
    assert anthropic_items(sent(prompt)) == [
        ("text", "user", "turn it on"),
        ("use", "a1", "lights_on", {"q": "hall"}), ("use", "a2", "weather", {"city": "Oslo"}),
        ("result", "a1", "lit", False), ("result", "a2", '{"t": 4}', True),
        ("text", "assistant", "done"), ("text", "user", "thanks")]


def test_two_rounds_keep_their_own_ids_in_order() -> None:
    first, second = (call("c1"),), (call("c1", "weather"),)
    prompt = tool_prompt(ASK, ToolCalls(first), results_for(first, "one"), Message("ashley", "ok"),
                         Message("person", "again"), ToolCalls(second), results_for(second, "two"))
    kinds = [item[0] for item in anthropic_items(sent(prompt))]
    assert kinds == ["text", "use", "result", "text", "text", "use", "result"]
    names = [item[2] for item in anthropic_items(sent(prompt)) if item[0] == "use"]
    assert names == ["lights_on", "weather"]


def test_a_tool_use_response_becomes_tool_use_with_ids_names_and_parsed_arguments() -> None:
    provider, _ = anthropic_provider(Answer(body=anthropic_tool_body(
        ("toolu_1", "lights_on", {"q": "hall", "n": 2, "deep": {"x": [1, 2]}}), ("toolu_2", "weather", {}))))
    got = ask(provider, tool_prompt(ASK))
    assert isinstance(got, ToolUse)
    assert got.calls == ToolCalls((ToolCall("toolu_1", "lights_on", {"q": "hall", "n": 2, "deep": {"x": [1, 2]}}),
                                   ToolCall("toolu_2", "weather", {})))
    assert got.usage == ANTHROPIC_USAGE


def test_a_reply_with_tools_offered_is_still_a_completion() -> None:
    provider, _ = anthropic_provider(Answer(body=anthropic_body()))
    got = ask(provider, tool_prompt(ASK))
    assert isinstance(got, Completion) and got.output.spoken == "Hello there."


def test_tool_choice_none_still_reads_a_reply() -> None:
    provider, _ = anthropic_provider(Answer(body=anthropic_body()))
    assert isinstance(ask(provider, one_round(tool_choice="none")), Completion)


@pytest.mark.parametrize("bad", [[1, 2], "text", 3, None], ids=["list", "string", "number", "null"])
def test_non_object_arguments_fail_invalid_output(bad: object) -> None:
    provider, _ = anthropic_provider(Answer(body=anthropic_tool_body(("toolu_1", "lights_on", bad))))
    with pytest.raises(ProviderFailed) as caught:
        ask(provider, tool_prompt(ASK))
    assert caught.value.failure == "invalid_output"
    assert caught.value.usage == ANTHROPIC_USAGE


def test_one_bad_call_among_good_ones_fails_the_whole_response() -> None:
    provider, _ = anthropic_provider(Answer(body=anthropic_tool_body(
        ("toolu_1", "lights_on", {}), ("toolu_2", "weather", [1]))))
    with pytest.raises(ProviderFailed) as caught:
        ask(provider, tool_prompt(ASK))
    assert caught.value.failure == "invalid_output"


def test_tool_calls_under_tool_choice_none_fail_invalid_output() -> None:
    provider, _ = anthropic_provider(USE)
    with pytest.raises(ProviderFailed) as caught:
        ask(provider, one_round(tool_choice="none"))
    assert caught.value.failure == "invalid_output"


def test_tool_calls_with_no_tools_offered_fail_invalid_output() -> None:
    provider, _ = anthropic_provider(USE)
    with pytest.raises(ProviderFailed) as caught:
        ask(provider, tool_prompt(ASK, tools=()))
    assert caught.value.failure == "invalid_output"


def test_a_failure_message_names_no_tool_or_argument() -> None:
    provider, _ = anthropic_provider(Answer(body=anthropic_tool_body(("toolu_1", "zqSecretTool", ["zqSecretArg"]))))
    with pytest.raises(ProviderFailed) as caught:
        ask(provider, tool_prompt(ASK))
    assert "zqSecretTool" not in str(caught.value) and "zqSecretArg" not in str(caught.value)


def test_tools_in_one_request_do_not_leak_into_the_next() -> None:
    provider, stand = anthropic_provider(Answer(body=anthropic_body()))
    ask(provider, tool_prompt(ASK))
    ask(provider, tool_prompt(ASK, tools=()))
    assert stand.sent[0]["tools"] and not stand.sent[1].get("tools")
