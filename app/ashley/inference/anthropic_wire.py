"""The exchange in the Messages API's shapes and back: tools, tool choice, history entries as turns, and the tool calls
a response asks for. Only `AnthropicProvider` uses it."""

import base64
import hashlib
import json

import anthropic
from anthropic.types import Message as AnthropicMessage
from anthropic.types import (CacheControlEphemeralParam, ContentBlockParam, ImageBlockParam, MessageParam, TextBlockParam, ToolChoiceParam,
                             ToolParam, ToolResultBlockParam, ToolUseBlock, ToolUseBlockParam)
from pydantic import BaseModel, TypeAdapter, ValidationError

from .model import (MOMENT_LABEL, Entry, Message, SystemPrompt, ToolCall, ToolCalls, ToolChoice, ToolResult, ToolResults,
                    ToolSpec)


def tools(specs: tuple[ToolSpec, ...]) -> list[ToolParam]:
    """The tools as the API takes them, a cache breakpoint on the last so the whole list is read across messages."""
    found: list[ToolParam] = [{"name": s.name, "description": s.description, "input_schema": dict(s.parameters)}
                              for s in specs]
    if found:
        found[-1]["cache_control"] = {"type": "ephemeral"}
    return found


def reply_schema(output: type[BaseModel]) -> dict[str, object]:
    """The schema the Messages API is sent as `output_config.format` for `output`."""
    return dict(anthropic.transform_schema(output.model_json_schema()))


def system(prompt: SystemPrompt) -> list[TextBlockParam]:
    """The system prompt as one block, its stable part, with a cache breakpoint. Its moment goes after the history
    (`with_moment`)."""
    return [{"type": "text", "text": prompt.stable, "cache_control": {"type": "ephemeral"}}]


def with_moment(turns: list[MessageParam], moment: str) -> list[MessageParam]:
    """`turns` with the moment as the last block of the last user turn, after any cache breakpoint on it, so history
    and tool rounds stay a prefix that does not move with the clock. When the last turn is not a user turn (or there are
    none) the moment is a user turn of its own."""
    if not moment:
        return turns
    block: TextBlockParam = {"type": "text", "text": f"{MOMENT_LABEL}\n{moment}"}
    if turns and turns[-1]["role"] == "user":
        content = turns[-1]["content"]
        blocks: list[ContentBlockParam] = ([{"type": "text", "text": content}] if isinstance(content, str)
                                           else [b for b in content if isinstance(b, dict)])
        return [*turns[:-1], {"role": "user", "content": [*blocks, block]}]
    return [*turns, {"role": "user", "content": [block]}]


def tool_choice(choice: ToolChoice) -> ToolChoiceParam:
    if choice == "auto":
        return {"type": "auto"}
    return {"type": "none"}


def messages(entries: tuple[Entry, ...]) -> list[MessageParam]:
    """One turn per entry: her tool calls are an assistant turn of `tool_use` blocks, their results a user turn of
    `tool_result` blocks."""
    return [_turn(entry) for entry in entries]


def cache_tail(turns: list[MessageParam]) -> list[MessageParam]:
    """`turns` with a cache breakpoint on the last block of the last turn, so the next tool round of the same turn reads
    the whole history written by this one (prompt-caching.md, "Multi-turn conversations"). A string turn becomes one
    text block to carry it."""
    if not turns:
        return turns
    last = turns[-1]
    content = last["content"] if isinstance(last["content"], str) else list(last["content"])
    blocks: list[ContentBlockParam] = ([{"type": "text", "text": content}] if isinstance(content, str)
                                       else [b for b in content if isinstance(b, dict)])
    if not blocks or len(blocks) != len(content if isinstance(content, list) else blocks):
        return turns
    blocks[-1] = _breakpoint(blocks[-1])
    return [*turns[:-1], {"role": last["role"], "content": blocks}]


def _breakpoint(block: ContentBlockParam) -> ContentBlockParam:
    """`block` with a cache breakpoint; the blocks `_turn` builds are text, `tool_use` and `tool_result`."""
    mark: CacheControlEphemeralParam = {"type": "ephemeral"}
    if block["type"] == "text":
        return {**block, "cache_control": mark}
    if block["type"] == "tool_use":
        return {**block, "cache_control": mark}
    if block["type"] == "tool_result":
        return {**block, "cache_control": mark}
    return block


def layer_hashes(tool_params: object, stable: str, turns: object) -> dict[str, str]:
    """A short hash of each cached layer as sent, to attribute a cache miss to the layer that changed: `tools`, the
    `stable` system text, and `tail`, every turn up to the breakpoint."""
    return {"tools": _short(tool_params), "stable": _short(stable), "tail": _short(turns)}


def _short(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()[:12]


def _turn(entry: Entry) -> MessageParam:
    if isinstance(entry, Message):
        return {"role": "user" if entry.author == "person" else "assistant", "content": entry.text}
    if isinstance(entry, ToolCalls):
        uses: list[ToolUseBlockParam] = [{"type": "tool_use", "id": c.id, "name": c.name, "input": dict(c.arguments)}
                                         for c in entry.calls]
        return {"role": "assistant", "content": uses}
    return {"role": "user", "content": _results(entry)}


def _results(entry: ToolResults) -> list[ToolResultBlockParam]:
    return [{"type": "tool_result", "tool_use_id": r.call_id, "content": _seen(r), "is_error": r.is_error}
            for r in entry.results]


def _seen(result: ToolResult) -> str | list[TextBlockParam | ImageBlockParam]:
    """The result's text, then each picture as an image block, which a `tool_result` may hold."""
    if not result.images:
        return result.content
    text: TextBlockParam = {"type": "text", "text": result.content}
    pictures: list[ImageBlockParam] = [
        {"type": "image", "source": {"type": "base64", "media_type": i.media_type,
                                     "data": base64.b64encode(i.data).decode("ascii")}} for i in result.images]
    return [text, *pictures]


def calls(response: AnthropicMessage) -> list[ToolCall] | None:
    """The `tool_use` blocks of a response, in order; None when one carries an input that is not a JSON object."""
    found: list[ToolCall] = []
    for block in response.content:
        if isinstance(block, ToolUseBlock):
            arguments = _object(block.input)
            if arguments is None:
                return None
            found.append(ToolCall(block.id, block.name, arguments))
    return found


def _object(value: object) -> dict[str, object] | None:
    """`value` as a JSON object. The SDK types `input` as one but builds its models unvalidated, so a server's
    array or string arrives as itself."""
    try:
        return _OBJECT.validate_python(value, strict=True)
    except ValidationError:
        return None


_OBJECT = TypeAdapter(dict[str, object])
