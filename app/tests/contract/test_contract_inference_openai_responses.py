"""`OpenAIResponsesProvider` over `POST /v1/responses`: the request it sends (instructions, input items, strict
`text.format`, `reasoning`, `store` off, function tools), the reply, tool calls, refusals and failures it maps, the
usage it reports, and `check_params`. The answers are built from the API reference, not captured live."""

import json
from typing import Any

import pytest
from ashley.inference.model import Image, Message, SystemPrompt, ToolCall, ToolCalls, ToolResult, ToolResults, Usage
from ashley.inference.provider import Completion, ProviderFailed, ProviderRefused, ToolUse
from ashley.inference.reply import Reply
from inference_responses_support import responses_body, responses_provider
from inference_support import answered, settle
from inference_tools_support import TOOLS, call, one_round, tool_prompt
from inference_tools_wire_support import ask
from inference_wire_support import MARK, REPLY, STATUS_ERROR, STATUS_UNAVAILABLE, Answer, openai_error

OK = Answer(body=responses_body())
PARAMS: dict[str, object] = {"max_output_tokens": 50}
ASK = Message("person", "turn it on")


def sent(prompt_: Any, params: dict[str, object] | None = None, answer: Answer = OK) -> dict[str, Any]:
    provider, stand = responses_provider(answer)
    ask(provider, prompt_, params=params or PARAMS)
    return stand.sent[0]


def failure(answer: Answer, prompt_: Any = None) -> ProviderFailed:
    provider, _ = responses_provider(answer)
    with pytest.raises(ProviderFailed) as caught:
        ask(provider, prompt_ or tool_prompt(ASK), params=PARAMS)
    return caught.value


def test_the_request_goes_to_responses_with_model_limit_instructions_and_nothing_stored() -> None:
    provider, stand = responses_provider(OK)
    answered(settle(provider.complete("gpt-test-9", {"max_output_tokens": 777}, SystemPrompt("be brief"),
                                      (ASK,), (), "auto", Reply, 4.5)))
    body = stand.sent[0]
    assert stand.path == "/v1/responses" and stand.read_timeout == 4.5
    assert (body["model"], body["max_output_tokens"], body["instructions"], body["store"]) == (
        "gpt-test-9", 777, "be brief", False)
    assert "messages" not in body and "max_completion_tokens" not in body


def test_the_reply_schema_is_the_strict_text_format() -> None:
    fmt = sent(tool_prompt(ASK))["text"]["format"]
    assert (fmt["type"], fmt["name"], fmt["strict"]) == ("json_schema", "reply", True)
    assert {"spoken", "text", "answers"} <= set(fmt["schema"]["properties"]) and fmt["schema"]["additionalProperties"] is False


def test_reasoning_effort_is_sent_as_reasoning_and_left_out_when_unset() -> None:
    assert sent(tool_prompt(ASK), {**PARAMS, "reasoning_effort": "low"})["reasoning"] == {"effort": "low"}
    assert "reasoning" not in sent(tool_prompt(ASK))


def test_tools_are_flat_non_strict_function_tools_with_their_schema_untouched() -> None:
    body = sent(tool_prompt(ASK))
    assert body["tools"] == [{"type": "function", "name": t.name, "description": t.description,
                              "parameters": dict(t.parameters), "strict": False} for t in TOOLS]
    assert body["tool_choice"] == "auto"


def test_tool_choice_none_keeps_the_tools_and_no_tools_sends_neither_field() -> None:
    body = sent(one_round(tool_choice="none"))
    assert body["tool_choice"] == "none" and len(body["tools"]) == len(TOOLS)
    bare = sent(tool_prompt(ASK, tools=()))
    assert "tools" not in bare and "tool_choice" not in bare


def test_history_is_input_items_in_order_and_the_moment_comes_last() -> None:
    calls = (call("a1", "lights_on", q="hall"), call("a2", "weather", city="Oslo"))
    prompt = tool_prompt(ASK, ToolCalls(calls), ToolResults((ToolResult("a1", "lit"), ToolResult("a2", "cold"))),
                         Message("ashley", "done"), Message("person", "thanks"))
    items = sent(prompt)["input"]
    assert [(i.get("role"), i.get("type")) for i in items[:7]] == [
        ("user", None), (None, "function_call"), (None, "function_call"), (None, "function_call_output"),
        (None, "function_call_output"), ("assistant", None), ("user", None)]
    assert [(i["call_id"], i["name"], json.loads(i["arguments"])) for i in items[1:3]] == [
        ("a1", "lights_on", {"q": "hall"}), ("a2", "weather", {"city": "Oslo"})]
    assert [(i["call_id"], i["output"]) for i in items[3:5]] == [("a1", "lit"), ("a2", "cold")]


def test_a_past_call_is_sent_without_the_response_item_id() -> None:
    (use,) = [i for i in sent(one_round())["input"] if i.get("type") == "function_call"]
    assert "id" not in use and isinstance(use["arguments"], str)


def test_an_error_result_is_wrapped_and_a_picture_rides_in_the_output_list() -> None:
    calls = (call("e1"), call("p1"))
    shown = ToolResults((ToolResult("e1", "bad", True), ToolResult("p1", "see", False, (Image("image/png", b"\x89PNG"),))))
    outputs = {i["call_id"]: i["output"] for i in sent(tool_prompt(ASK, ToolCalls(calls), shown))["input"]
               if i.get("type") == "function_call_output"}
    assert json.loads(outputs["e1"]) == {"is_error": True, "content": "bad"}
    assert outputs["p1"][0] == {"type": "input_text", "text": "see"}
    assert outputs["p1"][1]["type"] == "input_image" and outputs["p1"][1]["image_url"].startswith("data:image/png;base64,")


def test_a_reply_is_a_completion_with_its_usage() -> None:
    provider, _ = responses_provider(Answer(body=responses_body(reasoning=True)))
    got = ask(provider, tool_prompt(ASK), params=PARAMS)
    assert isinstance(got, Completion) and got.output == Reply.model_validate(REPLY)
    assert got.usage == Usage(50, 7, 40, 10)


@pytest.mark.parametrize(("input_tokens", "cached", "cache_write", "expect"), [
    (100, 40, 10, Usage(50, 7, 40, 10)), (100, 100, 0, Usage(0, 7, 100, 0)),
    (100, 0, 0, Usage(100, 7, 0, 0)), (20, 5, 4, Usage(11, 7, 5, 4))])
def test_cache_reads_and_writes_are_split_out_of_the_input_tokens(
        input_tokens: int, cached: int, cache_write: int, expect: Usage) -> None:
    body = responses_body(input_tokens=input_tokens, cached=cached, cache_write=cache_write)
    assert ask(responses_provider(Answer(body=body))[0], tool_prompt(ASK), params=PARAMS).usage == expect


def test_function_call_items_become_tool_use_with_call_ids_and_parsed_arguments() -> None:
    body = responses_body(text=None, reasoning=True, calls=(("call_1", "lights_on", '{"q": "hall", "d": {"x": [1]}}'),
                                                           ("call_2", "weather", "{}")))
    got = ask(responses_provider(Answer(body=body))[0], tool_prompt(ASK), params=PARAMS)
    assert isinstance(got, ToolUse) and got.usage == Usage(50, 7, 40, 10)
    assert got.calls == ToolCalls((ToolCall("call_1", "lights_on", {"q": "hall", "d": {"x": [1]}}),
                                   ToolCall("call_2", "weather", {})))


@pytest.mark.parametrize("bad", ["[1]", '"s"', "null", "not json", '{"q": '])
def test_non_object_arguments_fail_invalid_output_with_the_usage(bad: str) -> None:
    caught = failure(Answer(body=responses_body(text=None, calls=(("c", "zqTool", bad),))))
    assert caught.failure == "invalid_output" and caught.usage == Usage(50, 7, 40, 10) and "zqTool" not in str(caught)


def test_a_call_that_is_not_a_function_call_fails_invalid_output() -> None:
    body = responses_body(text=None)
    body["output"].append({"id": "x1", "type": "web_search_call", "status": "completed"})
    assert failure(Answer(body=body)).failure == "invalid_output"


@pytest.mark.parametrize("prompt_", [one_round(tool_choice="none"), tool_prompt(ASK, tools=())], ids=["none", "no-tools"])
def test_tool_calls_that_were_not_allowed_fail_invalid_output(prompt_: Any) -> None:
    body = responses_body(text=None, calls=(("c1", "lights_on", "{}"),))
    assert failure(Answer(body=body), prompt_).failure == "invalid_output"


def test_repeated_call_ids_fail_invalid_output() -> None:
    body = responses_body(text=None, calls=(("c1", "lights_on", "{}"), ("c1", "weather", "{}")))
    assert failure(Answer(body=body)).failure == "invalid_output"


def test_a_refusal_part_raises_refused_with_the_usage() -> None:
    provider, _ = responses_provider(Answer(body=responses_body(text=None, refusal="no")))
    with pytest.raises(ProviderRefused) as caught:
        ask(provider, tool_prompt(ASK), params=PARAMS)
    assert caught.value.usage == Usage(50, 7, 40, 10)


def test_a_content_filter_stop_is_a_refusal() -> None:
    provider, _ = responses_provider(Answer(body=responses_body(text="{", status="incomplete", incomplete="content_filter")))
    with pytest.raises(ProviderRefused):
        ask(provider, tool_prompt(ASK), params=PARAMS)


def test_a_reply_cut_off_at_the_token_limit_is_invalid_output_and_cut_off() -> None:
    caught = failure(Answer(body=responses_body(text='{"spoken": "He', status="incomplete", incomplete="max_output_tokens")))
    assert caught.failure == "invalid_output" and caught.cut_off and caught.usage == Usage(50, 7, 40, 10)


@pytest.mark.parametrize("text", ["", "not json", '{"spoken": 3}', "[1]"])
def test_text_that_is_not_the_schema_is_invalid_output(text: str) -> None:
    assert failure(Answer(body=responses_body(text=text))).failure == "invalid_output"


@pytest.mark.parametrize(("code", "kind"), [("server_error", "unavailable"), ("rate_limit_exceeded", "unavailable"),
                                            ("invalid_prompt", "error")])
def test_a_failed_response_fails_by_its_error_code(code: str, kind: str) -> None:
    caught = failure(Answer(body=responses_body(text=None, status="failed", error_code=code)))
    assert caught.failure == kind and code in str(caught)


@pytest.mark.parametrize("status", STATUS_UNAVAILABLE)
def test_statuses_that_cannot_serve_are_unavailable_and_never_echo_the_message(status: int) -> None:
    caught = failure(openai_error(status))
    assert caught.failure == "unavailable" and str(status) in str(caught) and MARK not in str(caught)


@pytest.mark.parametrize("status", STATUS_ERROR)
def test_other_statuses_are_errors_carrying_the_providers_message(status: int) -> None:
    caught = failure(openai_error(status))
    assert caught.failure == "error" and MARK in str(caught)


@pytest.mark.parametrize("raises", ["timeout", "connect"])
def test_a_timeout_or_refused_connection_is_unavailable(raises: str) -> None:
    assert failure(Answer(raises=raises)).failure == "unavailable"


def test_a_body_that_is_not_json_is_an_error() -> None:
    assert failure(Answer(raw=b"<html>")).failure == "error"


@pytest.mark.parametrize("params", [{"max_output_tokens": 16}, {"max_output_tokens": 10**6, "reasoning_effort": "none"},
                                    {"max_output_tokens": 50, "reasoning_effort": "xhigh"}])
def test_valid_params_are_accepted(params: dict[str, object]) -> None:
    responses_provider(OK)[0].check_params(params)


@pytest.mark.parametrize(("params", "culprit"), [
    ({}, "max_output_tokens"), ({"max_output_tokens": 15}, "max_output_tokens"),
    ({"max_output_tokens": True}, "max_output_tokens"), ({"max_output_tokens": "50"}, "max_output_tokens"),
    ({"max_output_tokens": 50, "reasoning_effort": "extreme"}, "reasoning_effort"),
    ({"max_output_tokens": 50, "max_completion_tokens": 50}, "max_completion_tokens"),
    ({"max_output_tokens": 50, "temperature": 1}, "temperature")])
def test_params_it_would_reject_raise_value_error_naming_the_parameter(params: dict[str, object], culprit: str) -> None:
    with pytest.raises(ValueError, match=culprit):
        responses_provider(OK)[0].check_params(params)


def test_it_is_also_the_transcriber_under_its_name() -> None:
    provider, _ = responses_provider(OK, name="openai")
    provider.check_transcribe_params({"language": "en"})
    assert provider.name == "openai"
