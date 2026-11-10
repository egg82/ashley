"""The exchange in Chat Completions' shapes and back: tools, tool choice, history entries as messages, and the tool
calls a response asks for. Only `OpenAICompatibleProvider` uses it.

Chat Completions has no error flag on a tool message, so a result with `is_error` is sent as the JSON object
`{"is_error": true, "content": <its content>}`; any other result is sent as its content alone.

A result's pictures cannot ride in its tool message, so `messages` sends them in a user message right after the
results, each after a line `PICTURE_LABEL` and its call id.

Fields a server adds to a tool call beyond the Chat Completions ones (Gemini's `extra_content`, which holds the thought
signature it requires back) are kept in `ToolCall.provider_data` and sent back verbatim on the same call."""

import base64
import json

import openai
from openai.types.chat import (ChatCompletionAssistantMessageParam, ChatCompletionContentPartParam,
                               ChatCompletionFunctionToolParam,
                               ChatCompletionMessage, ChatCompletionMessageFunctionToolCall,
                               ChatCompletionMessageFunctionToolCallParam, ChatCompletionMessageParam,
                               ChatCompletionToolChoiceOptionParam, ChatCompletionUserMessageParam)
from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError, with_config

from .model import MOMENT_LABEL, Entry, Message, SystemPrompt, ToolCall, ToolCalls, ToolChoice, ToolResult, ToolSpec


PICTURE_LABEL = "[A picture from the tool result of call"


def tools(specs: tuple[ToolSpec, ...]) -> list[ChatCompletionFunctionToolParam]:
    return [{"type": "function",
             "function": {"name": s.name, "description": s.description, "parameters": dict(s.parameters)}}
            for s in specs]


def reply_schema(output: type[BaseModel]) -> dict[str, object]:
    """The schema Chat Completions is sent as the strict `json_schema` response format for `output`."""
    return dict(openai.pydantic_function_tool(output, name="reply")["function"].get("parameters", {}))


def tool_choice(choice: ToolChoice) -> ChatCompletionToolChoiceOptionParam:
    return choice


def messages(system: SystemPrompt, entries: tuple[Entry, ...]) -> list[ChatCompletionMessageParam]:
    """The stable system prompt first, then one message per entry, except that results become one `tool` message each,
    then the moment as a user message of its own."""
    out: list[ChatCompletionMessageParam] = [{"role": "system", "content": system.stable}]
    for entry in entries:
        if isinstance(entry, Message):
            out.append({"role": "user", "content": entry.text} if entry.author == "person"
                       else {"role": "assistant", "content": entry.text})
        elif isinstance(entry, ToolCalls):
            out.append(_asked(entry))
        else:
            out.extend({"role": "tool", "tool_call_id": r.call_id, "content": _result_text(r)} for r in entry.results)
            shown = _pictures(entry.results)
            if shown is not None:
                out.append(shown)
    if system.moment:
        out.append({"role": "user", "content": f"{MOMENT_LABEL}\n{system.moment}"})
    return out


def _pictures(results: tuple[ToolResult, ...]) -> ChatCompletionUserMessageParam | None:
    """Tool messages are text alone, so the pictures the results carry go in one user message right after them, each
    after a line naming the call it came from; None when there are none."""
    parts: list[ChatCompletionContentPartParam] = []
    for r in results:
        for image in r.images:
            url = f"data:{image.media_type};base64,{base64.b64encode(image.data).decode('ascii')}"
            parts.append({"type": "text", "text": f"{PICTURE_LABEL} {r.call_id}:"})
            parts.append({"type": "image_url", "image_url": {"url": url}})
    return {"role": "user", "content": parts} if parts else None


def _asked(entry: ToolCalls) -> ChatCompletionAssistantMessageParam:
    calls: list[ChatCompletionMessageFunctionToolCallParam] = [_echoed(c) for c in entry.calls]
    return {"role": "assistant", "content": None, "tool_calls": calls}


@with_config(ConfigDict(extra="allow"))
class _EchoedCall(ChatCompletionMessageFunctionToolCallParam, total=False):
    """A function call as sent back, carrying the server's own fields beside the declared ones."""


_ECHOED = TypeAdapter(_EchoedCall)


def _echoed(call: ToolCall) -> _EchoedCall:
    return _ECHOED.validate_python({**call.provider_data, "type": "function", "id": call.id,
                                    "function": {"name": call.name, "arguments": json.dumps(dict(call.arguments))}})


def _result_text(result: ToolResult) -> str:
    return json.dumps({"is_error": True, "content": result.content}) if result.is_error else result.content


def calls(message: ChatCompletionMessage) -> list[ToolCall] | None:
    """The function calls a message asks for, in order; None when one is not a function call or its arguments are
    not a JSON object."""
    found: list[ToolCall] = []
    for call in message.tool_calls or ():
        if not isinstance(call, ChatCompletionMessageFunctionToolCall):
            return None
        arguments = _object(call.function.arguments)
        if arguments is None:
            return None
        found.append(ToolCall(call.id, call.function.name, arguments, dict(call.model_extra or {})))
    return found


def _object(text: str) -> dict[str, object] | None:
    try:
        return _OBJECT.validate_json(text, strict=True)
    except ValidationError:
        return None


_OBJECT = TypeAdapter(dict[str, object])
