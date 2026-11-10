"""What both providers promise alike, against real SDK clients over an in-process stand-in server: a valid reply,
refusals, replies that are cut off or do not match the schema, every status class, timeouts and dropped connections,
no retry, and failure messages that never carry the request or the response."""

import json
from importlib import resources
from collections.abc import Callable
from dataclasses import dataclass

import pytest
from ashley.inference.model import Message, SystemPrompt, Usage
from ashley.inference.provider import Completion, Provider, ProviderFailed, ProviderRefused
from ashley.inference.reply import Reply
from inference_support import answered, settle
from inference_wire_support import (MARK, REPLY, STATUS_ERROR, STATUS_UNAVAILABLE, Answer, StandIn, anthropic_body,
                                    anthropic_error, anthropic_provider, openai_body, openai_error, openai_provider)
from pydantic import BaseModel

REQ = "zqREQUEST5521"
MESSAGES = (Message("person", f"hello {REQ}"), Message("ashley", "hi"), Message("person", f"again {REQ}"))


@dataclass(frozen=True)
class Wire:
    label: str
    make: Callable[..., tuple[Provider, StandIn]]
    reply: Callable[[str], Answer]
    cut_off: Callable[[str], Answer]
    refusal: Callable[[], Answer]
    error: Callable[..., Answer]
    params: dict[str, object]
    usage: Usage


ANTHROPIC = Wire(
    "anthropic", anthropic_provider,
    lambda text: Answer(body=anthropic_body(text)),
    lambda text: Answer(body=anthropic_body(text, stop="max_tokens")),
    lambda: Answer(body=anthropic_body(stop="refusal")),
    anthropic_error, {"max_tokens": 1024}, Usage(11, 22, 33, 44))
OPENAI = Wire(
    "openai", openai_provider,
    lambda text: Answer(body=openai_body(text)),
    lambda text: Answer(body=openai_body(text, finish="length")),
    lambda: Answer(body=openai_body(None, refusal=f"I can't help with that {MARK}")),
    openai_error, {"max_completion_tokens": 1024}, Usage(50, 7, 40, 10))
WIRES = [ANTHROPIC, OPENAI]


def complete(provider: Provider, params: dict[str, object], messages: tuple[Message, ...] = MESSAGES,
             system: str = f"system {REQ}", model: str = "model-x", timeout_s: float = 9.0) -> Completion[Reply]:
    return answered(settle(provider.complete(model, params, SystemPrompt(system), messages, (), "auto", Reply, timeout_s)))


def failure_of(wire: Wire, *script: Answer) -> tuple[ProviderFailed, StandIn]:
    provider, stand = wire.make(*script)
    with pytest.raises(ProviderFailed) as caught:
        complete(provider, wire.params)
    return caught.value, stand


@pytest.mark.parametrize("wire", WIRES, ids=lambda w: w.label)
def test_a_valid_reply_is_returned_validated_with_the_usage_billed(wire: Wire) -> None:
    provider, stand = wire.make(wire.reply(json.dumps(REPLY)))
    got = complete(provider, wire.params)
    assert got.output == Reply.model_validate(REPLY)
    assert got.usage == wire.usage
    assert len(stand.requests) == 1


@pytest.mark.parametrize("wire", WIRES, ids=lambda w: w.label)
def test_the_output_type_asked_for_is_what_comes_back_and_what_the_request_describes(wire: Wire) -> None:
    class Verdict(BaseModel):
        yes: bool
        why: str

    provider, stand = wire.make(wire.reply('{"yes": true, "why": "because"}'))
    got = answered(settle(provider.complete("m", wire.params, SystemPrompt("sys"), MESSAGES, (), "auto", Verdict, 5)))
    assert got.output == Verdict(yes=True, why="because")
    assert "yes" in json.dumps(stand.sent[0]) and "why" in json.dumps(stand.sent[0])
    assert "spoken" not in json.dumps(stand.sent[0]).replace(REQ, "")


@pytest.mark.parametrize("wire", WIRES, ids=lambda w: w.label)
def test_each_provider_has_the_name_it_was_given(wire: Wire) -> None:
    assert wire.make(name="custom-name")[0].name == "custom-name"
    assert wire.make(name="other")[0].name == "other"


BAD_TEXTS = {
    "not json": f"I think {MARK} is great",
    "empty": "",
    "a json null": "null",
    "a json array": "[]",
    "a json string": json.dumps(MARK),
    "a field missing": json.dumps({"spoken": MARK}),
    "a field of the wrong type": json.dumps({"spoken": 5, "text": MARK}),
    "a field null": json.dumps({"spoken": MARK, "text": None}),
    "an extra field": json.dumps({**REPLY, "extra": MARK}),
    "truncated json": '{"spoken": "Hel',
}


@pytest.mark.parametrize("text", BAD_TEXTS.values(), ids=BAD_TEXTS.keys())
@pytest.mark.parametrize("wire", WIRES, ids=lambda w: w.label)
def test_a_reply_that_does_not_match_the_schema_fails_invalid_output_keeping_the_usage(wire: Wire, text: str) -> None:
    failed, _ = failure_of(wire, wire.reply(text))
    assert failed.failure == "invalid_output" and not failed.cut_off
    assert failed.usage == wire.usage, "the call was billed anyway"
    assert MARK not in str(failed) and REQ not in str(failed)


@pytest.mark.parametrize("text", ['{"spoken": "Hello th', json.dumps(REPLY)], ids=["partial json", "parses whole"])
@pytest.mark.parametrize("wire", WIRES, ids=lambda w: w.label)
def test_a_reply_cut_off_at_the_token_limit_fails_invalid_output_keeping_the_usage(wire: Wire, text: str) -> None:
    """The stop reason decides, not whether what arrived happens to parse."""
    failed, _ = failure_of(wire, wire.cut_off(text))
    assert failed.failure == "invalid_output" and failed.cut_off
    assert failed.usage == wire.usage


@pytest.mark.parametrize("wire", WIRES, ids=lambda w: w.label)
def test_a_refusal_raises_provider_refused_keeping_the_usage_and_not_the_words(wire: Wire) -> None:
    provider, _ = wire.make(wire.refusal())
    with pytest.raises(ProviderRefused) as caught:
        complete(provider, wire.params)
    assert caught.value.usage == wire.usage
    assert MARK not in str(caught.value) and REQ not in str(caught.value)


@pytest.mark.parametrize("status", STATUS_UNAVAILABLE)
@pytest.mark.parametrize("wire", WIRES, ids=lambda w: w.label)
def test_these_statuses_fail_unavailable(wire: Wire, status: int) -> None:
    failed, stand = failure_of(wire, wire.error(status))
    assert failed.failure == "unavailable"
    assert failed.usage is None
    assert str(status) in str(failed)
    assert len(stand.requests) == 1, "no retry of its own"


@pytest.mark.parametrize("status", STATUS_ERROR)
@pytest.mark.parametrize("wire", WIRES, ids=lambda w: w.label)
def test_every_other_status_fails_error(wire: Wire, status: int) -> None:
    failed, stand = failure_of(wire, wire.error(status))
    assert failed.failure == "error"
    assert failed.usage is None
    assert str(status) in str(failed)
    assert len(stand.requests) == 1


@pytest.mark.parametrize("status", STATUS_UNAVAILABLE)
@pytest.mark.parametrize("wire", WIRES, ids=lambda w: w.label)
def test_an_unavailable_failure_never_carries_the_request_or_the_response(wire: Wire, status: int) -> None:
    failed, _ = failure_of(wire, wire.error(status))
    assert MARK not in str(failed) and REQ not in str(failed)
    assert MARK not in repr(failed) and all(MARK not in str(a) for a in failed.args)


@pytest.mark.parametrize("status", STATUS_ERROR)
@pytest.mark.parametrize("wire", WIRES, ids=lambda w: w.label)
def test_an_error_status_names_the_providers_message_and_never_the_request(wire: Wire, status: int) -> None:
    failed, _ = failure_of(wire, wire.error(status))
    assert f"status={status} message='{MARK}'" in str(failed) and REQ not in str(failed)


@pytest.mark.parametrize("wire", WIRES, ids=lambda w: w.label)
def test_an_error_status_message_is_one_line_cut_to_the_configured_length(wire: Wire) -> None:
    limit = json.loads(resources.files("ashley.inference").joinpath("failures.json").read_text())["message_chars"]
    failed, _ = failure_of(wire, wire.error(400, f"first\n\nsecond {'x' * (limit * 2)}"))
    said = str(failed).split("message=", 1)[1]
    assert said.startswith("'first second x") and "\n" not in said and len(said) == limit + 2


@pytest.mark.parametrize("wire", WIRES, ids=lambda w: w.label)
def test_a_timeout_fails_unavailable_and_names_the_exception_type(wire: Wire) -> None:
    failed, stand = failure_of(wire, Answer(raises="timeout"))
    assert failed.failure == "unavailable"
    assert "APITimeoutError" in str(failed)
    assert REQ not in str(failed)
    assert len(stand.requests) == 1


@pytest.mark.parametrize("wire", WIRES, ids=lambda w: w.label)
def test_a_dropped_connection_fails_unavailable(wire: Wire) -> None:
    failed, _ = failure_of(wire, Answer(raises="connect"))
    assert failed.failure == "unavailable"
    assert "APIConnectionError" in str(failed)


@pytest.mark.parametrize("wire", WIRES, ids=lambda w: w.label)
def test_a_rate_limit_message_names_its_type_and_status_only(wire: Wire) -> None:
    failed, _ = failure_of(wire, wire.error(429))
    assert "RateLimitError" in str(failed) and "429" in str(failed)


@pytest.mark.parametrize("wire", WIRES, ids=lambda w: w.label)
def test_a_200_that_is_not_json_at_all_is_a_provider_failure_not_some_other_exception(wire: Wire) -> None:
    failed, _ = failure_of(wire, Answer(raw=f"<html>{MARK}</html>".encode()))
    assert failed.failure in ("invalid_output", "error")
    assert MARK not in str(failed)


@pytest.mark.parametrize("wire", WIRES, ids=lambda w: w.label)
def test_a_failure_does_not_poison_the_provider(wire: Wire) -> None:
    provider, stand = wire.make(wire.error(503), wire.reply(json.dumps(REPLY)))
    with pytest.raises(ProviderFailed):
        complete(provider, wire.params)
    assert complete(provider, wire.params).output == Reply.model_validate(REPLY)
    assert len(stand.requests) == 2


@pytest.mark.parametrize("wire", WIRES, ids=lambda w: w.label)
def test_the_timeout_asked_for_is_the_one_the_request_carries(wire: Wire) -> None:
    provider, stand = wire.make(wire.reply(json.dumps(REPLY)))
    complete(provider, wire.params, timeout_s=3.5)
    assert stand.read_timeout == 3.5
    complete(provider, wire.params, timeout_s=41)
    assert stand.read_timeout == 41

