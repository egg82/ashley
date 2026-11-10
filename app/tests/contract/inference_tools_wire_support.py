"""Wire shapes of tool use for the two real providers, taken from the installed SDKs' types: Anthropic `tool_use` and
`tool_result` blocks, OpenAI `tool_calls` and `tool` messages. Requests are read back from the stand-in server."""

import json
from typing import Any

from ashley.inference.model import Prompt, Usage
from ashley.inference.provider import Completion, Provider, ToolUse
from ashley.inference.reply import Reply
from inference_support import settle
from inference_wire_support import anthropic_body, openai_body, text_of

ANTHROPIC_USAGE = Usage(11, 22, 33, 44)
OPENAI_USAGE = Usage(50, 7, 40, 10)


def anthropic_tool_body(*uses: tuple[str, str, object], stop: str = "tool_use") -> dict[str, Any]:
    """A Messages response asking for tools: each use is (id, name, input)."""
    body = anthropic_body()
    body["content"] = [{"type": "tool_use", "id": i, "name": n, "input": a} for i, n, a in uses]
    body["stop_reason"] = stop
    return body


def openai_tool_body(*uses: tuple[str, str, str], finish: str = "tool_calls") -> dict[str, Any]:
    """A Chat Completions response asking for tools: each use is (id, name, arguments-as-the-JSON-string-sent)."""
    body = openai_body()
    message: dict[str, Any] = body["choices"][0]["message"]
    message["content"] = None
    message["tool_calls"] = [{"id": i, "type": "function", "function": {"name": n, "arguments": a}}
                             for i, n, a in uses]
    body["choices"][0]["finish_reason"] = finish
    return body


def ask(provider: Provider, prompt: Prompt, model: str = "m-test", params: dict[str, object] | None = None,
        timeout_s: float = 9.0) -> Completion[Reply] | ToolUse:
    return settle(provider.complete(model, params or {"max_tokens": 50, "max_completion_tokens": 50},
                                    prompt.system_for("default"), prompt.messages, prompt.tools, prompt.tool_choice,
                                    Reply, timeout_s))


def anthropic_items(body: dict[str, Any]) -> list[tuple[Any, ...]]:
    """The conversation as a flat, grouping-independent sequence: ('text', role, text), ('use', id, name, input),
    ('result', id, content, is_error)."""
    items: list[tuple[Any, ...]] = []
    for message in body["messages"]:
        content = message["content"]
        if isinstance(content, str):
            items.append(("text", message["role"], content))
            continue
        for block in content:
            if block["type"] == "text":
                items.append(("text", message["role"], block["text"]))
            elif block["type"] == "tool_use":
                assert message["role"] == "assistant"
                items.append(("use", block["id"], block["name"], block["input"]))
            else:
                assert block["type"] == "tool_result" and message["role"] == "user"
                items.append(("result", block["tool_use_id"], text_of(block["content"]), bool(block.get("is_error"))))
    return items


def openai_items(body: dict[str, Any]) -> list[tuple[Any, ...]]:
    """('text', role, text), ('use', id, name, parsed-arguments), ('result', id, content), skipping the system message."""
    items: list[tuple[Any, ...]] = []
    for message in body["messages"][1:]:
        if message["role"] == "tool":
            items.append(("result", message["tool_call_id"], text_of(message["content"])))
            continue
        if message.get("content"):
            items.append(("text", message["role"], text_of(message["content"])))
        tool_calls: list[dict[str, Any]] = message.get("tool_calls") or []
        for tc in tool_calls:
            assert tc["type"] == "function" and message["role"] == "assistant"
            items.append(("use", tc["id"], tc["function"]["name"], json.loads(tc["function"]["arguments"])))
    return items
