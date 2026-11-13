"""The exchange in the Responses API's shapes (`POST /v1/responses`) and back: tools, tool choice, history entries as
input items, and what a response holds. Only `OpenAIResponsesProvider` uses it; Chat Completions' shapes are
`openai_wire`.

The system prompt's stable part is `instructions`; the moment is a user item after the history. A past tool call is a
`function_call` item with only `call_id`, `name` and `arguments`: the response's own item id is never sent back, since
a call sent with its id must come with the reasoning item beside it, which a request with `store` off does not carry.
A result with `is_error` is wrapped as Chat Completions' is (`openai_wire.result_text`); its pictures ride in the
`function_call_output`'s content list, which takes images.

Tool parameters are sent non-strict: strict function calling needs every property required and no open objects, which
the app's tool schemas are not. The reply schema is the strict `text.format`, the one Chat Completions is sent."""

import base64
import json

from openai.types.responses import (EasyInputMessageParam, FunctionToolParam, Response, ResponseFunctionToolCall,
                                    ResponseFunctionToolCallParam, ResponseInputItemParam, ResponseOutputMessage,
                                    ResponseOutputRefusal, ResponseOutputText)
from openai.types.responses.response_function_call_output_item_list_param import ResponseFunctionCallOutputItemParam
from openai.types.responses.response_input_item_param import FunctionCallOutput
from openai.types.responses.tool_choice_options import ToolChoiceOptions
from pydantic import TypeAdapter, ValidationError

from .model import MOMENT_LABEL, Entry, Message, SystemPrompt, ToolCall, ToolCalls, ToolChoice, ToolResult, ToolSpec
from .openai_wire import reply_schema, result_text

__all__ = ["reply_schema", "tools", "tool_choice", "items", "calls", "refusal", "text"]


def tools(specs: tuple[ToolSpec, ...]) -> list[FunctionToolParam]:
    return [{"type": "function", "name": s.name, "description": s.description, "parameters": dict(s.parameters),
             "strict": False} for s in specs]


def tool_choice(choice: ToolChoice) -> ToolChoiceOptions:
    return choice


def items(system: SystemPrompt, entries: tuple[Entry, ...]) -> list[ResponseInputItemParam]:
    """One item per entry (a result is one `function_call_output` each), then the moment as a user item of its own."""
    out: list[ResponseInputItemParam] = []
    for entry in entries:
        if isinstance(entry, Message):
            message: EasyInputMessageParam = {"role": "user" if entry.author == "person" else "assistant",
                                              "content": entry.text}
            out.append(message)
        elif isinstance(entry, ToolCalls):
            out.extend(_asked(c) for c in entry.calls)
        else:
            out.extend(_answered(r) for r in entry.results)
    if system.moment:
        out.append({"role": "user", "content": f"{MOMENT_LABEL}\n{system.moment}"})
    return out


def _asked(call: ToolCall) -> ResponseFunctionToolCallParam:
    return {"type": "function_call", "call_id": call.id, "name": call.name,
            "arguments": json.dumps(dict(call.arguments))}


def _answered(result: ToolResult) -> FunctionCallOutput:
    text = result_text(result)
    if not result.images:
        return {"type": "function_call_output", "call_id": result.call_id, "output": text}
    parts: list[ResponseFunctionCallOutputItemParam] = [{"type": "input_text", "text": text}]
    parts.extend({"type": "input_image",
                  "image_url": f"data:{i.media_type};base64,{base64.b64encode(i.data).decode('ascii')}"}
                 for i in result.images)
    return {"type": "function_call_output", "call_id": result.call_id, "output": parts}


def calls(response: Response) -> list[ToolCall] | None:
    """The function calls a response asks for, in order; None when one is not a function call or its arguments are
    not a JSON object."""
    found: list[ToolCall] = []
    for item in response.output:
        if item.type in ("message", "reasoning"):
            continue
        if not isinstance(item, ResponseFunctionToolCall):
            return None
        arguments = _object(item.arguments)
        if arguments is None:
            return None
        found.append(ToolCall(item.call_id, item.name, arguments))
    return found


def refusal(response: Response) -> bool:
    """Whether the model declined: a message of the response holds a refusal part."""
    return any(isinstance(part, ResponseOutputRefusal) for message in _messages(response) for part in message.content)


def text(response: Response) -> str:
    """The reply text: every `output_text` part of every message, joined."""
    return "".join(part.text for message in _messages(response) for part in message.content
                   if isinstance(part, ResponseOutputText))


def _messages(response: Response) -> list[ResponseOutputMessage]:
    return [item for item in response.output if isinstance(item, ResponseOutputMessage)]


def _object(text: str) -> dict[str, object] | None:
    try:
        return _OBJECT.validate_json(text, strict=True)
    except ValidationError:
        return None


_OBJECT = TypeAdapter(dict[str, object])
