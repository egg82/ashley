"""`OpenAICompatibleProvider`: the Chat Completions request it sends (strict `json_schema` response format, the system
prompt first, messages in order, model, params, per-request timeout), the usage it reports, and `check_params`."""

import json
import re
from typing import Any

import pytest
from ashley.inference.model import Message, SystemPrompt, Usage
from ashley.inference.provider import Provider
from ashley.inference.reply import Reply
from inference_support import answered, settle
from inference_wire_support import REPLY, Answer, StandIn, openai_body, openai_provider, text_of

OK = Answer(body=openai_body())
SYSTEM = "You are Ashley. Be brief."
MESSAGES = (Message("person", "first"), Message("ashley", "second"), Message("person", "third"),
            Message("person", "fourth"))


def send(params: dict[str, object], messages: tuple[Message, ...] = MESSAGES, system: str = SYSTEM,
         model: str = "gpt-test-1", timeout_s: float = 9.0) -> tuple[dict[str, Any], StandIn]:
    provider, stand = openai_provider(OK)
    answered(settle(provider.complete(model, params, SystemPrompt(system), messages, (), "auto", Reply, timeout_s)))
    assert len(stand.requests) == 1
    return stand.sent[0], stand


def test_the_request_goes_to_chat_completions_with_the_model_and_the_token_limit() -> None:
    body, stand = send({"max_completion_tokens": 777}, model="gpt-test-9")
    assert stand.requests[0].method == "POST" and stand.path.endswith("/chat/completions")
    assert body["model"] == "gpt-test-9"
    assert body["max_completion_tokens"] == 777


EFFORTS = ("none", "minimal", "low", "medium", "high", "xhigh", "max")


@pytest.mark.parametrize("effort", EFFORTS)
def test_reasoning_effort_is_sent_when_given(effort: str) -> None:
    body, _ = send({"max_completion_tokens": 5, "reasoning_effort": effort})
    assert body["reasoning_effort"] == effort


def test_no_reasoning_effort_is_sent_when_none_was_given() -> None:
    body, _ = send({"max_completion_tokens": 5})
    assert body.get("reasoning_effort") is None


def test_the_schema_of_the_asked_for_output_is_a_strict_json_schema_response_format() -> None:
    body, _ = send({"max_completion_tokens": 5})
    fmt = body["response_format"]
    assert fmt["type"] == "json_schema"
    spec = fmt["json_schema"]
    assert spec["strict"] is True
    assert re.fullmatch(r"[A-Za-z0-9_-]{1,64}", spec["name"])
    schema = spec["schema"]
    assert schema["type"] == "object"
    assert set(schema["properties"]) == {"answers", "spoken", "text", "offer", "to_phone", "aloud", "memory", "used_facts", "escalate", "owed", "says"}
    assert set(schema["required"]) == {"answers", "spoken", "text", "offer", "to_phone", "aloud", "memory", "used_facts", "escalate", "owed", "says"}
    assert schema["additionalProperties"] is False
    act = schema["$defs"]["MemoryAct"]
    assert act["additionalProperties"] is False and set(act["required"]) == set(act["properties"]) == {"action", "facts"}
    assert "plain sentences" in json.dumps(schema), "the field descriptions travel with the schema"


def test_the_system_prompt_is_the_first_message_and_the_rest_follow_in_order() -> None:
    body, _ = send({"max_completion_tokens": 5})
    first, *rest = body["messages"]
    assert first["role"] in ("system", "developer")
    assert text_of(first["content"]) == SYSTEM
    assert [(m["role"], text_of(m["content"])) for m in rest] == [
        ("user", "first"), ("assistant", "second"), ("user", "third"), ("user", "fourth")]


def test_the_system_prompt_appears_once() -> None:
    body, _ = send({"max_completion_tokens": 5})
    assert [text_of(m["content"]) for m in body["messages"]].count(SYSTEM) == 1


def test_text_is_sent_verbatim() -> None:
    odd = (Message("person", ' quotes " and \\ and \n newlines, ünïcödé 🙂 {"json": true} '),)
    body, _ = send({"max_completion_tokens": 5}, odd, system="  spaced \n system  ")
    assert text_of(body["messages"][0]["content"]) == "  spaced \n system  "
    assert text_of(body["messages"][1]["content"]) == odd[0].text


def test_the_request_carries_the_timeout_asked_for() -> None:
    _, stand = send({"max_completion_tokens": 5}, timeout_s=2.5)
    assert stand.read_timeout == 2.5


def test_a_server_that_is_not_openai_is_addressed_the_same_way() -> None:
    """Gemini's and a local server's OpenAI endpoints take this same request: only the client's base URL differs."""
    provider, stand = openai_provider(OK, name="gemini")
    answered(settle(provider.complete("gemini-x", {"max_completion_tokens": 5},
                                      SystemPrompt(SYSTEM), MESSAGES, (), "auto", Reply, 5)))
    assert provider.name == "gemini"
    assert stand.sent[0]["model"] == "gemini-x"


# --- usage ---------------------------------------------------------------------------------------------------------


def usage_of(prompt_tokens: int = 100, completion_tokens: int = 7, cached: int | None = 40,
             cache_write: int | None = 10) -> Usage:
    provider, _ = openai_provider(Answer(body=openai_body(
        prompt_tokens=prompt_tokens, completion_tokens=completion_tokens, cached=cached, cache_write=cache_write)))
    return answered(settle(provider.complete("m", {"max_completion_tokens": 5},
                                             SystemPrompt(SYSTEM), MESSAGES, (), "auto", Reply, 5))).usage


def test_cache_reads_and_writes_are_split_out_of_the_prompt_tokens() -> None:
    """`input_tokens` excludes cache reads and writes (`model.Usage`), while OpenAI's `prompt_tokens` includes both."""
    assert usage_of(prompt_tokens=100, completion_tokens=7, cached=40, cache_write=10) == Usage(50, 7, 40, 10)
    assert usage_of(prompt_tokens=100, completion_tokens=7, cached=100, cache_write=0) == Usage(0, 7, 100, 0)
    assert usage_of(prompt_tokens=100, completion_tokens=7, cached=0, cache_write=100) == Usage(0, 7, 0, 100)


def test_reads_alone_and_writes_alone_are_each_split_out() -> None:
    assert usage_of(prompt_tokens=100, completion_tokens=7, cached=40, cache_write=None) == Usage(60, 7, 40, 0)
    assert usage_of(prompt_tokens=100, completion_tokens=7, cached=None, cache_write=30) == Usage(70, 7, 0, 30)


def test_no_cache_counts_means_the_whole_prompt_is_input() -> None:
    assert usage_of(prompt_tokens=100, completion_tokens=7, cached=None, cache_write=None) == Usage(100, 7, 0, 0)
    assert usage_of(prompt_tokens=100, completion_tokens=7, cached=0, cache_write=0) == Usage(100, 7, 0, 0)


def test_the_counts_do_not_swap() -> None:
    assert usage_of(prompt_tokens=20, completion_tokens=3, cached=4, cache_write=5) == Usage(11, 3, 4, 5)
    assert usage_of(prompt_tokens=20, completion_tokens=9, cached=5, cache_write=4) == Usage(11, 9, 5, 4)


def test_a_null_prompt_tokens_details_is_no_cache() -> None:
    body = openai_body()
    body["usage"]["prompt_tokens_details"] = None
    provider, _ = openai_provider(Answer(body=body))
    got = answered(settle(provider.complete("m", {"max_completion_tokens": 5},
                                            SystemPrompt(SYSTEM), MESSAGES, (), "auto", Reply, 5))).usage
    assert got == Usage(100, 7, 0, 0)


def test_null_counts_inside_the_details_are_zero() -> None:
    body = openai_body()
    body["usage"]["prompt_tokens_details"] = {"cached_tokens": None, "cache_write_tokens": None}
    provider, _ = openai_provider(Answer(body=body))
    got = answered(settle(provider.complete("m", {"max_completion_tokens": 5},
                                            SystemPrompt(SYSTEM), MESSAGES, (), "auto", Reply, 5))).usage
    assert got == Usage(100, 7, 0, 0)


# --- check_params ----------------------------------------------------------------------------------------------------


def checker() -> Provider:
    return openai_provider(OK)[0]


@pytest.mark.parametrize("params", [
    {"max_completion_tokens": 1}, {"max_completion_tokens": 4096}, {"max_completion_tokens": 10**6},
    *[{"max_completion_tokens": 5, "reasoning_effort": e} for e in EFFORTS],
])
def test_valid_params_are_accepted(params: dict[str, object]) -> None:
    checker().check_params(params)


@pytest.mark.parametrize(("params", "culprit"), [
    ({}, "max_completion_tokens"),
    ({"reasoning_effort": "low"}, "max_completion_tokens"),
    ({"max_completion_tokens": 0}, "max_completion_tokens"),
    ({"max_completion_tokens": -5}, "max_completion_tokens"),
    ({"max_completion_tokens": "100"}, "max_completion_tokens"),
    ({"max_completion_tokens": 1.5}, "max_completion_tokens"),
    ({"max_completion_tokens": None}, "max_completion_tokens"),
    ({"max_completion_tokens": True}, "max_completion_tokens"),
    ({"max_completion_tokens": 5, "reasoning_effort": "extreme"}, "reasoning_effort"),
    ({"max_completion_tokens": 5, "reasoning_effort": "HIGH"}, "reasoning_effort"),
    ({"max_completion_tokens": 5, "reasoning_effort": 3}, "reasoning_effort"),
    ({"max_completion_tokens": 5, "reasoning_effort": None}, "reasoning_effort"),
    ({"max_completion_tokens": 5, "temperature": 0.5}, "temperature"),
    ({"max_completion_tokens": 5, "max_tokens": 5}, "max_tokens"),
    ({"max_completion_tokens": 5, "effort": "low"}, "effort"),
])
def test_params_it_does_not_take_or_would_reject_raise_value_error_naming_the_parameter(
        params: dict[str, object], culprit: str) -> None:
    with pytest.raises(ValueError, match=culprit):
        checker().check_params(params)


def test_a_reply_is_still_read_when_the_params_are_the_minimum() -> None:
    provider, _ = openai_provider(Answer(body=openai_body()))
    got = answered(settle(provider.complete("m", {"max_completion_tokens": 5},
                                            SystemPrompt(SYSTEM), MESSAGES, (), "auto", Reply, 5))).output
    assert got == Reply.model_validate(REPLY)
