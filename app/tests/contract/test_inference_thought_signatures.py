"""Gemini's thought signatures over its OpenAI-compatible endpoint: a tool call's `extra_content` is kept in
`ToolCall.provider_data` and sent back verbatim on the same call; Anthropic ignores it. Wire shapes are the
"Signatures for OpenAI compatibility" examples in Gemini's thought-signature docs (parallel and sequential calls)."""

from typing import Any

from ashley.inference.model import Message, ToolCall, ToolCalls
from ashley.inference.provider import ToolUse
from inference_tools_support import TOOLS, results_for, tool_prompt
from inference_tools_wire_support import ask, openai_tool_body
from inference_wire_support import Answer, anthropic_body, anthropic_provider, openai_body, openai_provider

ASK = Message("person", "Check the weather in Paris and London.")
SIGNED_A = {"extra_content": {"google": {"thought_signature": "<Signature A>"}}}
SIGNED_B = {"extra_content": {"google": {"thought_signature": "<Signature B>"}}}


def gemini_parallel_body() -> dict[str, Any]:
    """Two parallel calls; only the first carries a signature, as Gemini sends them."""
    body = openai_tool_body(("function-call-1", "weather", '{"city":"Paris"}'),
                            ("function-call-2", "weather", '{"city":"London"}'))
    body["choices"][0]["message"]["tool_calls"][0].update(SIGNED_A)
    return body


def sent_calls(body: dict[str, Any]) -> list[dict[str, Any]]:
    """Every tool call of every assistant message in an OpenAI request, in order."""
    found: list[dict[str, Any]] = []
    for message in body["messages"]:
        if message["role"] == "assistant":
            found.extend(message.get("tool_calls") or [])
    return found


def test_a_signature_on_a_tool_call_is_kept_and_a_call_without_one_keeps_nothing() -> None:
    provider, _ = openai_provider(Answer(body=gemini_parallel_body()))
    got = ask(provider, tool_prompt(ASK))
    assert isinstance(got, ToolUse)
    first, second = got.calls.calls
    assert (first.id, first.name, first.arguments, first.provider_data) == (
        "function-call-1", "weather", {"city": "Paris"}, SIGNED_A)
    assert (second.id, second.arguments, second.provider_data) == ("function-call-2", {"city": "London"}, {})


def test_the_signature_goes_back_verbatim_on_the_same_call_and_nowhere_else() -> None:
    provider, _ = openai_provider(Answer(body=gemini_parallel_body()))
    got = ask(provider, tool_prompt(ASK))
    assert isinstance(got, ToolUse)
    provider, stand = openai_provider(Answer(body=openai_body()))
    ask(provider, tool_prompt(ASK, got.calls, results_for(got.calls.calls)))
    first, second = sent_calls(stand.sent[0])
    assert first == {"type": "function", "id": "function-call-1", **SIGNED_A,
                     "function": {"name": "weather", "arguments": '{"city": "Paris"}'}}
    assert "extra_content" not in second and second["id"] == "function-call-2"


def test_each_round_of_a_sequential_loop_sends_back_its_own_signature() -> None:
    a = ToolCall("function-call-1", "weather", {"city": "Oslo"}, SIGNED_A)
    b = ToolCall("function-call-2", "lights_on", {"q": "hall"}, SIGNED_B)
    provider, stand = openai_provider(Answer(body=openai_body()))
    ask(provider, tool_prompt(ASK, ToolCalls((a,)), results_for((a,)), ToolCalls((b,)), results_for((b,))))
    assert [(tc["id"], tc.get("extra_content")) for tc in sent_calls(stand.sent[0])] == [
        ("function-call-1", SIGNED_A["extra_content"]), ("function-call-2", SIGNED_B["extra_content"])]


def test_a_call_with_no_provider_data_is_sent_with_only_the_chat_completions_fields() -> None:
    plain = ToolCall("call_1", "lights_on", {"q": "hall"})
    provider, stand = openai_provider(Answer(body=openai_body()))
    ask(provider, tool_prompt(ASK, ToolCalls((plain,)), results_for((plain,))))
    assert [set(tc) for tc in sent_calls(stand.sent[0])] == [{"type", "id", "function"}]


def test_anthropic_ignores_provider_data() -> None:
    signed = ToolCall("toolu_1", "lights_on", {"q": "hall"}, SIGNED_A)
    provider, stand = anthropic_provider(Answer(body=anthropic_body()))
    ask(provider, tool_prompt(ASK, ToolCalls((signed,)), results_for((signed,)), tools=TOOLS))
    uses = [b for m in stand.sent[0]["messages"] if isinstance(m["content"], list) for b in m["content"]
            if b["type"] == "tool_use"]
    assert uses == [{"type": "tool_use", "id": "toolu_1", "name": "lights_on", "input": {"q": "hall"}}]
