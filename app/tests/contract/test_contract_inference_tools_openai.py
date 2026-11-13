"""`OpenAICompatibleProvider` with tools: the request carries `tools` and `tool_choice` in the Chat Completions format,
history entries are translated in order as assistant `tool_calls` and `tool` messages, and a `tool_calls` response
becomes `ToolUse`."""

import json
from typing import Any

import pytest
from ashley.inference.model import Message, Prompt, ToolCall, ToolCalls, ToolResult, ToolResults
from ashley.inference.provider import Completion, ProviderFailed, ToolUse
from inference_tools_support import TOOLS, call, one_round, results_for, tool_prompt
from inference_tools_wire_support import OPENAI_USAGE, ask, openai_items, openai_tool_body
from inference_wire_support import Answer, openai_body, openai_provider

ASK = Message("person", "turn it on")
USE = Answer(body=openai_tool_body(("call_1", "lights_on", '{"q": "hall"}')))


def sent(prompt_: Prompt, answer: Answer = Answer(body=openai_body())) -> dict[str, Any]:
    provider, stand = openai_provider(answer)
    ask(provider, prompt_)
    return stand.sent[0]


def test_the_tools_are_sent_as_function_tools_with_name_description_and_parameters() -> None:
    body = sent(tool_prompt(ASK))
    assert [(t["type"], t["function"]["name"], t["function"]["description"], t["function"]["parameters"])
            for t in body["tools"]] == [("function", t.name, t.description, dict(t.parameters)) for t in TOOLS]


def test_tool_choice_auto_is_sent_as_auto() -> None:
    assert sent(tool_prompt(ASK))["tool_choice"] == "auto"


def test_tool_choice_none_is_sent_as_none_with_the_tools_still_defined() -> None:
    body = sent(one_round(tool_choice="none"))
    assert body["tool_choice"] == "none"
    assert [t["function"]["name"] for t in body["tools"]] == [t.name for t in TOOLS]


def test_no_tools_means_no_tools_and_no_tool_choice_in_the_request() -> None:
    body = sent(tool_prompt(ASK, tools=()))
    assert not body.get("tools") and body.get("tool_choice") is None


def test_the_reply_schema_is_still_sent_when_tools_are() -> None:
    fmt = sent(tool_prompt(ASK))["response_format"]
    assert fmt["type"] == "json_schema" and set(fmt["json_schema"]["schema"]["properties"]) == {"answers", "spoken", "text", "offer", "to_phone", "aloud", "memory", "used_facts", "escalate", "owed", "says"}


def test_history_is_translated_in_order_with_ids_names_json_arguments_and_results() -> None:
    calls = (call("a1", "lights_on", q="hall"), call("a2", "weather", city="Oslo"))
    prompt = tool_prompt(ASK, ToolCalls(calls), ToolResults((ToolResult("a1", "lit"), ToolResult("a2", '{"t": 4}'))),
                         Message("ashley", "done"), Message("person", "thanks"))
    body = sent(prompt)
    assert openai_items(body) == [
        ("text", "user", "turn it on"),
        ("use", "a1", "lights_on", {"q": "hall"}), ("use", "a2", "weather", {"city": "Oslo"}),
        ("result", "a1", "lit"), ("result", "a2", '{"t": 4}'),
        ("text", "assistant", "done"), ("text", "user", "thanks")]


def test_the_arguments_of_a_past_call_are_sent_as_a_json_string() -> None:
    body = sent(one_round((call("a1", "lights_on", q="hall"),)))
    (calls_message,) = [m for m in body["messages"] if m.get("tool_calls")]
    arguments = calls_message["tool_calls"][0]["function"]["arguments"]
    assert isinstance(arguments, str) and json.loads(arguments) == {"q": "hall"}


def test_two_rounds_keep_their_own_ids_in_order() -> None:
    first, second = (call("c1"),), (call("c1", "weather"),)
    prompt = tool_prompt(ASK, ToolCalls(first), results_for(first, "one"), Message("ashley", "ok"),
                         Message("person", "again"), ToolCalls(second), results_for(second, "two"))
    items = openai_items(sent(prompt))
    assert [i[0] for i in items] == ["text", "use", "result", "text", "text", "use", "result"]
    assert [i[2] for i in items if i[0] == "use"] == ["lights_on", "weather"]


def test_a_tool_calls_response_becomes_tool_use_with_ids_names_and_parsed_arguments() -> None:
    provider, _ = openai_provider(Answer(body=openai_tool_body(
        ("call_1", "lights_on", '{"q": "hall", "n": 2, "deep": {"x": [1, 2]}}'), ("call_2", "weather", "{}"))))
    got = ask(provider, tool_prompt(ASK))
    assert isinstance(got, ToolUse)
    assert got.calls == ToolCalls((ToolCall("call_1", "lights_on", {"q": "hall", "n": 2, "deep": {"x": [1, 2]}}),
                                   ToolCall("call_2", "weather", {})))
    assert got.usage == OPENAI_USAGE


def test_a_reply_with_tools_offered_is_still_a_completion() -> None:
    provider, _ = openai_provider(Answer(body=openai_body()))
    got = ask(provider, tool_prompt(ASK))
    assert isinstance(got, Completion) and got.output.spoken == "Hello there."


def test_tool_choice_none_still_reads_a_reply() -> None:
    provider, _ = openai_provider(Answer(body=openai_body()))
    assert isinstance(ask(provider, one_round(tool_choice="none")), Completion)


@pytest.mark.parametrize("bad", ["[1, 2]", '"text"', "3", "null", "not json", '{"q": '],
                         ids=["list", "string", "number", "null", "not-json", "truncated"])
def test_non_object_arguments_fail_invalid_output(bad: str) -> None:
    provider, _ = openai_provider(Answer(body=openai_tool_body(("call_1", "lights_on", bad))))
    with pytest.raises(ProviderFailed) as caught:
        ask(provider, tool_prompt(ASK))
    assert caught.value.failure == "invalid_output"
    assert caught.value.usage == OPENAI_USAGE


def test_one_bad_call_among_good_ones_fails_the_whole_response() -> None:
    provider, _ = openai_provider(Answer(body=openai_tool_body(
        ("call_1", "lights_on", "{}"), ("call_2", "weather", "[1]"))))
    with pytest.raises(ProviderFailed) as caught:
        ask(provider, tool_prompt(ASK))
    assert caught.value.failure == "invalid_output"


def test_tool_calls_under_tool_choice_none_fail_invalid_output() -> None:
    provider, _ = openai_provider(USE)
    with pytest.raises(ProviderFailed) as caught:
        ask(provider, one_round(tool_choice="none"))
    assert caught.value.failure == "invalid_output"


def test_tool_calls_with_no_tools_offered_fail_invalid_output() -> None:
    provider, _ = openai_provider(USE)
    with pytest.raises(ProviderFailed) as caught:
        ask(provider, tool_prompt(ASK, tools=()))
    assert caught.value.failure == "invalid_output"


def test_a_failure_message_names_no_tool_or_argument() -> None:
    provider, _ = openai_provider(Answer(body=openai_tool_body(("call_1", "zqSecretTool", '["zqSecretArg"]'))))
    with pytest.raises(ProviderFailed) as caught:
        ask(provider, tool_prompt(ASK))
    assert "zqSecretTool" not in str(caught.value) and "zqSecretArg" not in str(caught.value)


def test_tools_in_one_request_do_not_leak_into_the_next() -> None:
    provider, stand = openai_provider(Answer(body=openai_body()))
    ask(provider, tool_prompt(ASK))
    ask(provider, tool_prompt(ASK, tools=()))
    assert stand.sent[0]["tools"] and not stand.sent[1].get("tools")
