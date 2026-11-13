"""The three provider implementations. Each takes a configured async SDK client, so wiring decides keys and endpoints
and a test can point one at a stand-in server.

`AnthropicProvider` calls the Messages API with the schema as `output_config.format` (structured outputs) and three
cache breakpoints: the last tool, the end of the system prompt's stable part, and the last block of the last turn,
so the next tool round and the next message read the history. The prompt's `moment` is the last block of the last
user turn, after that breakpoint, so the clock moving rewrites none of them. `OpenAICompatibleProvider` sends it as a
user message after the history. Each call logs `inference.cache_layers` with a hash of each cached layer (never content) and the cache
tokens read and written. Params: `max_tokens` (int > 0, required), `effort` (`low`, `medium`, `high`, `xhigh`, `max`).

`OpenAICompatibleProvider` calls Chat Completions with the schema as a strict `json_schema` response format, the one
API ChatGPT, Gemini's OpenAI endpoint and local servers (Ollama, vLLM, llama.cpp) all speak. Params:
`max_completion_tokens` (int > 0, required), `reasoning_effort` (`none`, `minimal`, `low`, `medium`, `high`, `xhigh`,
`max`; which a model accepts is the model's business). Usage counts cached reads and cache writes apart from input.
It is also a `Transcriber` for `transcribe` routes (`openai_stt`).

`OpenAIResponsesProvider` calls OpenAI's Responses API (`POST /v1/responses`, `store` off) with the schema as the
strict `text.format`, the one API that takes tools with `reasoning.effort`. Params: `max_output_tokens` (int of at least
16, required), `reasoning_effort` (as above). A response `incomplete` for `max_output_tokens` is cut off; one
`incomplete` for `content_filter`, or holding a refusal part, is a refusal; one `failed` fails by its error code. Usage
and tool history as for Chat Completions; the shapes are `openai_responses_wire`. It is also a `Transcriber`, as the
`openai` name serves both.

All three: a refusal (Anthropic `stop_reason` `refusal`; OpenAI `message.refusal` set) raises ProviderRefused; a reply cut
off at the token limit or not matching the schema fails `invalid_output`; a timeout, connection failure, 408, 409,
429, 5xx, 401, 402 or 403 fails `unavailable`; any other status fails `error`. A failure message names the
exception type and status; an `error` status adds the provider's own message (`message=`), one line cut to
`failures.json` `message_chars`, since a 400 describes the request's shape (a refused parameter), while an
`unavailable` status never adds it (a 401 can echo a key). Neither retries: the client is built with `max_retries=0`.

Tools go with the schema when offered; with none offered, neither `tools` nor `tool_choice` is sent. Anthropic: a
`stop_reason` of `tool_use` is a `ToolUse`; the API renders tool definitions before the system prompt, so the second
breakpoint covers both and the first keeps the tools when only the system prompt differs. OpenAI: a `finish_reason` of
`tool_calls`, or any tool calls on the message, is a `ToolUse`; Responses: any `function_call` item. Tool calls that name none, repeat an id, are not function calls, carry arguments that are not a JSON object, or
arrive with no tools offered or under `none` fail `invalid_output`. History in each wire format: `anthropic_wire`,
`openai_wire`."""

import json
import logging
from collections.abc import AsyncIterator, Iterable, Mapping
from importlib import resources
from typing import Literal, TypeVar

import anthropic
import openai
from anthropic import AsyncAnthropic
from anthropic.types import Message as AnthropicMessage
from anthropic.types import OutputConfigParam
from openai import AsyncOpenAI, Omit, omit
from openai.types import CompletionUsage, ReasoningEffort
from openai.types.chat import ChatCompletion
from openai.types.responses import Response, ResponseUsage
from pydantic import BaseModel, TypeAdapter, ValidationError

from .. import logs
from . import anthropic_wire, openai_responses_wire, openai_stt, openai_wire
from .model import Entry, SystemPrompt, ToolCall, ToolCalls, ToolChoice, ToolSpec, Usage
from .provider import Completion, Provider, ProviderFailed, ProviderRefused, ToolUse, status_failure
from .speech import AudioFormat
from .speech_provider import Transcriber

log = logging.getLogger("ashley.inference")
T = TypeVar("T", bound=BaseModel)
_OBJECT = TypeAdapter(dict[str, object])
_MESSAGE_CHARS: int = json.loads(resources.files("ashley.inference").joinpath("failures.json").read_text())["message_chars"]

_E = TypeVar("_E")
_ANTHROPIC_EFFORT: dict[str, Literal["low", "medium", "high", "xhigh", "max"]] = {
    "low": "low", "medium": "medium", "high": "high", "xhigh": "xhigh", "max": "max"}
_OPENAI_EFFORT: dict[str, Literal["none", "minimal", "low", "medium", "high", "xhigh", "max"]] = {
    "none": "none", "minimal": "minimal", "low": "low", "medium": "medium", "high": "high", "xhigh": "xhigh",
    "max": "max"}


def _status_reason(e: anthropic.APIStatusError | openai.APIStatusError) -> str:
    """The failure message of an HTTP error status: the exception type and status, plus the provider's message as one
    line cut to `_MESSAGE_CHARS` when the status fails `error`."""
    reason = f"{type(e).__name__} status={e.status_code}"
    if status_failure(e.status_code) != "error":
        return reason
    return f"{reason} message={' '.join(_error_message(e.body).split())[:_MESSAGE_CHARS]!r}"


def _error_message(body: object) -> str:
    """The `message` of an error body (Anthropic nests it under `error`, OpenAI's SDK hands over the inner object);
    empty when the body has none, never the raw body."""
    outer = _object(body)
    message = _object(outer.get("error", outer)).get("message")
    return message if isinstance(message, str) else ""


def _object(value: object) -> dict[str, object]:
    try:
        return _OBJECT.validate_python(value)
    except ValidationError:
        return {}


def _untrusted(response: object) -> object:
    """An SDK result as what it may really be: both SDKs are typed to return their parsed reply, but a 200 whose body
    is not JSON comes back as a str."""
    return response


def _check_params(params: Mapping[str, object], size_key: str, effort_key: str, efforts: Iterable[str]) -> None:
    unknown = sorted(set(params) - {size_key, effort_key})
    if unknown:
        raise ValueError(f"unknown parameter {unknown[0]!r}")
    size = params.get(size_key)
    if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
        raise ValueError(f"{size_key} is required and must be a whole number above 0")
    allowed = list(efforts)
    if effort_key in params and params[effort_key] not in allowed:
        raise ValueError(f"{effort_key} must be one of {', '.join(allowed)}")


def _int_param(params: Mapping[str, object], key: str) -> int:
    value = params[key]
    assert isinstance(value, int)
    return value


def _decode(text: str | None, output: type[T], usage: Usage | None) -> Completion[T]:
    """The reply text as `output`, or invalid_output; a success with no reported usage counts as zero tokens."""
    try:
        return Completion(output.model_validate_json(text or ""), usage or Usage(0, 0))
    except ValueError as e:
        raise ProviderFailed("invalid_output", f"{type(e).__name__}: reply does not match the schema", usage) from e


def _output_config(output: type[BaseModel], params: Mapping[str, object]) -> OutputConfigParam:
    schema = anthropic_wire.reply_schema(output)
    config = OutputConfigParam(format={"type": "json_schema", "schema": schema})
    effort = _lookup(_ANTHROPIC_EFFORT, params.get("effort"))
    if effort is not None:
        config["effort"] = effort
    return config


def _openai_effort(params: Mapping[str, object]) -> ReasoningEffort | Omit:
    return _lookup(_OPENAI_EFFORT, params.get("reasoning_effort")) or omit


def _lookup(table: Mapping[str, _E], key: object) -> _E | None:
    return table.get(key) if isinstance(key, str) else None


def _tool_use(found: list[ToolCall] | None, tools: tuple[ToolSpec, ...], tool_choice: ToolChoice,
              usage: Usage | None) -> ToolUse:
    """The calls a response asked for, or invalid_output when they are malformed, empty, repeat an id, or were not
    allowed."""
    if found is None:
        raise ProviderFailed("invalid_output", "a tool call is not a function call with object arguments", usage)
    if not found:
        raise ProviderFailed("invalid_output", "asked for tools but named none", usage)
    if not tools or tool_choice == "none":
        raise ProviderFailed("invalid_output", "asked for tools when none were allowed", usage)
    if len({c.id for c in found}) != len(found):
        raise ProviderFailed("invalid_output", "tool call ids repeat", usage)
    return ToolUse(ToolCalls(tuple(found)), usage or Usage(0, 0))


def _openai_usage(usage: CompletionUsage | None) -> Usage | None:
    if usage is None:
        return None
    details = usage.prompt_tokens_details
    read = (details.cached_tokens or 0) if details else 0
    written = (details.cache_write_tokens or 0) if details else 0
    return Usage(usage.prompt_tokens - read - written, usage.completion_tokens, read, written)


def _responses_usage(usage: ResponseUsage | None) -> Usage | None:
    if usage is None:
        return None
    read, written = usage.input_tokens_details.cached_tokens, usage.input_tokens_details.cache_write_tokens
    return Usage(usage.input_tokens - read - written, usage.output_tokens, read, written)


_MIN_OUTPUT_TOKENS = 16
_SERVER_SIDE = frozenset({"server_error", "rate_limit_exceeded"})


def _responses_unfinished(response: Response, usage: Usage | None) -> ProviderFailed | ProviderRefused | None:
    """What a response that did not complete is: a refusal, a cut-off reply, or a failure; None when it completed."""
    reason = response.incomplete_details.reason if response.incomplete_details else None
    if reason == "content_filter":
        return ProviderRefused("the model refused", usage)
    if reason == "max_output_tokens":
        return ProviderFailed("invalid_output", "reply cut off at the token limit", usage, cut_off=True)
    if response.status == "failed":
        code = response.error.code if response.error else "unknown"
        return ProviderFailed("unavailable" if code in _SERVER_SIDE else "error", f"response failed code={code}", usage)
    if response.status != "completed":
        return ProviderFailed("error", f"response not completed status={response.status}", usage)
    return None


class AnthropicProvider(Provider):
    def __init__(self, name: str, client: AsyncAnthropic) -> None:
        self._name = name
        self._client = client

    @property
    def name(self) -> str:
        return self._name

    def check_params(self, params: Mapping[str, object]) -> None:
        _check_params(params, "max_tokens", "effort", _ANTHROPIC_EFFORT)

    async def complete(self, model: str, params: Mapping[str, object], system: SystemPrompt, messages: tuple[Entry, ...],
                       tools: tuple[ToolSpec, ...], tool_choice: ToolChoice, output: type[T],
                       timeout_s: float) -> Completion[T] | ToolUse:
        config = _output_config(output, params)
        turns = anthropic_wire.cache_tail(anthropic_wire.messages(messages))
        wire_tools = anthropic_wire.tools(tools)
        try:
            sent = anthropic_wire.with_moment(turns, system.moment)
            response = _untrusted(await self._client.messages.create(
                model=model, max_tokens=_int_param(params, "max_tokens"), timeout=timeout_s, output_config=config,
                system=anthropic_wire.system(system),
                messages=sent,
                tools=wire_tools if tools else anthropic.omit,
                tool_choice=anthropic_wire.tool_choice(tool_choice) if tools else anthropic.omit))
        except anthropic.APIStatusError as e:
            raise ProviderFailed(status_failure(e.status_code), _status_reason(e)) from e
        except anthropic.APIConnectionError as e:
            raise ProviderFailed("unavailable", type(e).__name__) from e
        except Exception as e:
            raise ProviderFailed("error", type(e).__name__) from e
        if not isinstance(response, AnthropicMessage):
            raise ProviderFailed("error", f"unexpected response body: {type(response).__name__}")
        usage = Usage(response.usage.input_tokens, response.usage.output_tokens,
                      response.usage.cache_read_input_tokens or 0, response.usage.cache_creation_input_tokens or 0)
        logs.info(log, "inference.cache_layers", provider=self._name, model=model, turns=len(turns),
                  cache_read=usage.cache_read_tokens, cache_write=usage.cache_write_tokens,
                  **anthropic_wire.layer_hashes(wire_tools, system.stable, turns))
        if response.stop_reason == "refusal":
            raise ProviderRefused("the model refused", usage)
        if response.stop_reason == "max_tokens":
            raise ProviderFailed("invalid_output", "reply cut off at the token limit", usage, cut_off=True)
        if response.stop_reason == "tool_use":
            return _tool_use(anthropic_wire.calls(response), tools, tool_choice, usage)
        text = "".join(block.text for block in response.content if block.type == "text")
        return _decode(text, output, usage)


class OpenAICompatibleProvider(Provider, Transcriber):
    def __init__(self, name: str, client: AsyncOpenAI) -> None:
        self._name = name
        self._client = client

    @property
    def name(self) -> str:
        return self._name

    def check_params(self, params: Mapping[str, object]) -> None:
        _check_params(params, "max_completion_tokens", "reasoning_effort", _OPENAI_EFFORT)

    def check_transcribe_params(self, params: Mapping[str, object]) -> None:
        openai_stt.check_params(params)

    async def transcribe(self, model: str, params: Mapping[str, object], format: AudioFormat,
                         chunks: AsyncIterator[bytes], timeout_s: float, language: str | None = None) -> str:
        return await openai_stt.transcribe(self._client, model, params, format, chunks, timeout_s, language)

    async def complete(self, model: str, params: Mapping[str, object], system: SystemPrompt, messages: tuple[Entry, ...],
                       tools: tuple[ToolSpec, ...], tool_choice: ToolChoice, output: type[T],
                       timeout_s: float) -> Completion[T] | ToolUse:
        schema = openai_wire.reply_schema(output)
        try:
            response = _untrusted(await self._client.chat.completions.create(
                model=model, timeout=timeout_s, max_completion_tokens=_int_param(params, "max_completion_tokens"),
                response_format={"type": "json_schema",
                                 "json_schema": {"name": "reply", "strict": True, "schema": schema}},
                messages=openai_wire.messages(system, messages),
                tools=openai_wire.tools(tools) if tools else omit,
                tool_choice=openai_wire.tool_choice(tool_choice) if tools else omit,
                reasoning_effort=_openai_effort(params)))
        except openai.APIStatusError as e:
            raise ProviderFailed(status_failure(e.status_code), _status_reason(e)) from e
        except openai.APIConnectionError as e:
            raise ProviderFailed("unavailable", type(e).__name__) from e
        except Exception as e:
            raise ProviderFailed("error", type(e).__name__) from e
        if not isinstance(response, ChatCompletion):
            raise ProviderFailed("error", f"unexpected response body: {type(response).__name__}")
        usage = _openai_usage(response.usage)
        choice = response.choices[0]
        if choice.message.refusal:
            raise ProviderRefused("the model refused", usage)
        if choice.finish_reason == "length":
            raise ProviderFailed("invalid_output", "reply cut off at the token limit", usage, cut_off=True)
        if choice.finish_reason == "tool_calls" or choice.message.tool_calls:
            return _tool_use(openai_wire.calls(choice.message), tools, tool_choice, usage)
        return _decode(choice.message.content, output, usage)


class OpenAIResponsesProvider(Provider, Transcriber):
    def __init__(self, name: str, client: AsyncOpenAI) -> None:
        self._name = name
        self._client = client

    @property
    def name(self) -> str:
        return self._name

    def check_params(self, params: Mapping[str, object]) -> None:
        _check_params(params, "max_output_tokens", "reasoning_effort", _OPENAI_EFFORT)
        if _int_param(params, "max_output_tokens") < _MIN_OUTPUT_TOKENS:
            raise ValueError(f"max_output_tokens must be at least {_MIN_OUTPUT_TOKENS}")

    def check_transcribe_params(self, params: Mapping[str, object]) -> None:
        openai_stt.check_params(params)

    async def transcribe(self, model: str, params: Mapping[str, object], format: AudioFormat,
                         chunks: AsyncIterator[bytes], timeout_s: float, language: str | None = None) -> str:
        return await openai_stt.transcribe(self._client, model, params, format, chunks, timeout_s, language)

    async def complete(self, model: str, params: Mapping[str, object], system: SystemPrompt, messages: tuple[Entry, ...],
                       tools: tuple[ToolSpec, ...], tool_choice: ToolChoice, output: type[T],
                       timeout_s: float) -> Completion[T] | ToolUse:
        effort = _openai_effort(params)
        try:
            response = _untrusted(await self._client.responses.create(
                model=model, timeout=timeout_s, store=False, max_output_tokens=_int_param(params, "max_output_tokens"),
                instructions=system.stable, input=openai_responses_wire.items(system, messages),
                text={"format": {"type": "json_schema", "name": "reply", "strict": True,
                                 "schema": openai_responses_wire.reply_schema(output)}},
                tools=openai_responses_wire.tools(tools) if tools else omit,
                tool_choice=openai_responses_wire.tool_choice(tool_choice) if tools else omit,
                reasoning=omit if isinstance(effort, Omit) else {"effort": effort}))
        except openai.APIStatusError as e:
            raise ProviderFailed(status_failure(e.status_code), _status_reason(e)) from e
        except openai.APIConnectionError as e:
            raise ProviderFailed("unavailable", type(e).__name__) from e
        except Exception as e:
            raise ProviderFailed("error", type(e).__name__) from e
        if not isinstance(response, Response):
            raise ProviderFailed("error", f"unexpected response body: {type(response).__name__}")
        usage = _responses_usage(response.usage)
        if openai_responses_wire.refusal(response):
            raise ProviderRefused("the model refused", usage)
        stopped = _responses_unfinished(response, usage)
        if stopped is not None:
            raise stopped
        found = openai_responses_wire.calls(response)
        if found is None or found:
            return _tool_use(found, tools, tool_choice, usage)
        return _decode(openai_responses_wire.text(response), output, usage)
