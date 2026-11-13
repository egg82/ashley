"""`AnthropicProvider`: the Messages API request it sends (schema as `output_config.format`, the cached system prompt,
messages in order, model, params, per-request timeout), the usage it reports, and `check_params`."""

import json
from typing import Any

import pytest
from ashley.inference.model import Message, SystemPrompt, Usage
from ashley.inference.provider import Provider
from ashley.inference.reply import Reply
from inference_support import answered, settle
from inference_wire_support import REPLY, Answer, StandIn, anthropic_body, anthropic_provider, system_blocks, text_of

OK = Answer(body=anthropic_body())
SYSTEM = "You are Ashley. Be brief."
MESSAGES = (Message("person", "first"), Message("ashley", "second"), Message("person", "third"),
            Message("person", "fourth"))


def send(params: dict[str, object], messages: tuple[Message, ...] = MESSAGES, system: str = SYSTEM,
         model: str = "claude-test-1", timeout_s: float = 9.0) -> tuple[dict[str, Any], StandIn]:
    provider, stand = anthropic_provider(OK)
    answered(settle(provider.complete(model, params, SystemPrompt(system), messages, (), "auto", Reply, timeout_s)))
    assert len(stand.requests) == 1
    return stand.sent[0], stand


def test_the_request_goes_to_the_messages_endpoint_with_the_model_and_max_tokens() -> None:
    body, stand = send({"max_tokens": 777}, model="claude-test-9")
    assert stand.requests[0].method == "POST" and stand.path.endswith("/v1/messages")
    assert body["model"] == "claude-test-9"
    assert body["max_tokens"] == 777


@pytest.mark.parametrize("effort", ["low", "medium", "high", "xhigh", "max"])
def test_effort_is_sent_as_output_config_effort(effort: str) -> None:
    body, _ = send({"max_tokens": 5, "effort": effort})
    assert body["output_config"]["effort"] == effort


def test_no_effort_is_sent_when_none_was_given() -> None:
    body, _ = send({"max_tokens": 5})
    assert body["output_config"].get("effort") is None


def test_the_schema_of_the_asked_for_output_is_the_json_schema_format() -> None:
    body, _ = send({"max_tokens": 5})
    fmt = body["output_config"]["format"]
    assert fmt["type"] == "json_schema"
    schema = fmt["schema"]
    assert schema["type"] == "object"
    assert set(schema["properties"]) == {"answers", "spoken", "text", "offer", "to_phone", "aloud", "memory", "used_facts", "escalate", "owed", "says"}
    assert set(schema["required"]) == {"answers", "spoken", "text", "offer", "to_phone", "aloud", "memory", "used_facts", "escalate", "owed", "says"}
    assert schema["additionalProperties"] is False
    act = schema["$defs"]["MemoryAct"]
    assert act["additionalProperties"] is False and set(act["required"]) == set(act["properties"]) == {"action", "facts"}
    assert "plain sentences" in json.dumps(schema), "the field descriptions travel with the schema"
    assert "default" not in json.dumps(schema), "a default would reach the model as text and lean its answer"


def test_the_system_prompt_is_sent_whole_and_cached() -> None:
    body, _ = send({"max_tokens": 5})
    assert text_of(body["system"]) == SYSTEM
    blocks = system_blocks(body["system"])
    marks: list[dict[str, Any]] = [b.get("cache_control") or {} for b in blocks]
    top: dict[str, Any] = body.get("cache_control") or {}
    assert any(m.get("type") == "ephemeral" for m in [*marks, top]), "the system prompt is cached"


def test_the_messages_go_in_order_as_user_and_assistant_turns() -> None:
    body, _ = send({"max_tokens": 5})
    assert [(m["role"], text_of(m["content"])) for m in body["messages"]] == [
        ("user", "first"), ("assistant", "second"), ("user", "third"), ("user", "fourth")]


def test_the_system_prompt_is_not_also_sent_as_a_message() -> None:
    body, _ = send({"max_tokens": 5})
    assert all(SYSTEM not in text_of(m["content"]) for m in body["messages"])


def test_text_is_sent_verbatim() -> None:
    odd = (Message("person", ' quotes " and \\ and \n newlines, ünïcödé 🙂 {"json": true} '),)
    body, _ = send({"max_tokens": 5}, odd, system="  spaced \n system  ")
    assert text_of(body["messages"][0]["content"]) == odd[0].text
    assert text_of(body["system"]) == "  spaced \n system  "


def test_the_request_carries_the_timeout_asked_for() -> None:
    _, stand = send({"max_tokens": 5}, timeout_s=2.5)
    assert stand.read_timeout == 2.5


# --- usage ---------------------------------------------------------------------------------------------------------


def usage_of(input_tokens: int = 11, output_tokens: int = 22, cache_read: int | None = 33,
             cache_write: int | None = 44) -> Usage:
    provider, _ = anthropic_provider(Answer(body=anthropic_body(
        input_tokens=input_tokens, output_tokens=output_tokens, cache_read=cache_read, cache_write=cache_write)))
    return answered(settle(provider.complete("m", {"max_tokens": 5}, SystemPrompt(SYSTEM), MESSAGES, (), "auto", Reply, 5))).usage


def test_usage_maps_input_output_cache_read_and_cache_write() -> None:
    assert usage_of(input_tokens=11, output_tokens=22, cache_read=33, cache_write=44) == Usage(11, 22, 33, 44)


def test_absent_cache_counts_are_zero() -> None:
    assert usage_of(input_tokens=5, output_tokens=6, cache_read=None, cache_write=None) == Usage(5, 6, 0, 0)
    assert usage_of(cache_read=9, cache_write=None).cache_write_tokens == 0
    assert usage_of(cache_read=None, cache_write=9).cache_read_tokens == 0


def test_a_null_cache_count_is_zero() -> None:
    body = anthropic_body()
    body["usage"]["cache_read_input_tokens"] = None
    body["usage"]["cache_creation_input_tokens"] = None
    provider, _ = anthropic_provider(Answer(body=body))
    assert answered(settle(provider.complete("m", {"max_tokens": 5},
                                             SystemPrompt(SYSTEM), MESSAGES, (), "auto", Reply, 5))).usage == Usage(11, 22, 0, 0)


def test_the_four_counts_do_not_swap() -> None:
    assert usage_of(input_tokens=1, output_tokens=2, cache_read=3, cache_write=4) == Usage(1, 2, 3, 4)
    assert usage_of(input_tokens=4, output_tokens=3, cache_read=2, cache_write=1) == Usage(4, 3, 2, 1)


# --- check_params ----------------------------------------------------------------------------------------------------


def checker() -> Provider:
    return anthropic_provider(OK)[0]


@pytest.mark.parametrize("params", [
    {"max_tokens": 1}, {"max_tokens": 4096}, {"max_tokens": 10**6},
    *[{"max_tokens": 5, "effort": e} for e in ("low", "medium", "high", "xhigh", "max")],
])
def test_valid_params_are_accepted(params: dict[str, object]) -> None:
    checker().check_params(params)


@pytest.mark.parametrize(("params", "culprit"), [
    ({}, "max_tokens"),
    ({"effort": "low"}, "max_tokens"),
    ({"max_tokens": 0}, "max_tokens"),
    ({"max_tokens": -5}, "max_tokens"),
    ({"max_tokens": "100"}, "max_tokens"),
    ({"max_tokens": 1.5}, "max_tokens"),
    ({"max_tokens": None}, "max_tokens"),
    ({"max_tokens": True}, "max_tokens"),
    ({"max_tokens": 5, "effort": "extreme"}, "effort"),
    ({"max_tokens": 5, "effort": "minimal"}, "effort"),
    ({"max_tokens": 5, "effort": "none"}, "effort"),
    ({"max_tokens": 5, "effort": "LOW"}, "effort"),
    ({"max_tokens": 5, "effort": 3}, "effort"),
    ({"max_tokens": 5, "effort": None}, "effort"),
    ({"max_tokens": 5, "temperature": 0.5}, "temperature"),
    ({"max_tokens": 5, "max_completion_tokens": 5}, "max_completion_tokens"),
    ({"max_tokens": 5, "reasoning_effort": "low"}, "reasoning_effort"),
])
def test_params_it_does_not_take_or_would_reject_raise_value_error_naming_the_parameter(
        params: dict[str, object], culprit: str) -> None:
    with pytest.raises(ValueError, match=culprit):
        checker().check_params(params)


def test_a_reply_is_still_read_when_the_params_are_the_minimum() -> None:
    provider, _ = anthropic_provider(Answer(body=anthropic_body()))
    assert answered(settle(provider.complete("m", {"max_tokens": 5},
                                             SystemPrompt(SYSTEM), MESSAGES, (), "auto", Reply, 5))).output == Reply.model_validate(REPLY)
