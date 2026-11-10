"""Stand-in servers for the provider tests: each real SDK client is built with an `http_client` whose transport answers
in process, so the request an SDK really sends is captured and the answer is a real wire shape. No network."""

import json
from dataclasses import dataclass
from typing import Any

import httpx
import httpx2
from anthropic import AsyncAnthropic
from ashley.inference.providers import AnthropicProvider, OpenAICompatibleProvider
from openai import AsyncOpenAI

MARK = "zqPLANTED9082"
REPLY: dict[str, str] = {"spoken": "Hello there.", "text": "Hello **there**."}
STATUS_UNAVAILABLE = (401, 402, 403, 408, 409, 429, 500, 502, 503, 504, 529)
STATUS_ERROR = (400, 404, 405, 413, 422)


@dataclass(frozen=True)
class Answer:
    """What the stand-in server does with one request: respond `status` with `body` (JSON) or `raw` bytes, or fail the
    connection (`raises` is `timeout` or `connect`)."""

    status: int = 200
    body: object = None
    raw: bytes | None = None
    raises: str | None = None


def anthropic_body(text: str = json.dumps(REPLY), stop: str = "end_turn", input_tokens: int = 11,
                   output_tokens: int = 22, cache_read: int | None = 33, cache_write: int | None = 44) -> dict[str, Any]:
    usage: dict[str, Any] = {"input_tokens": input_tokens, "output_tokens": output_tokens}
    if cache_read is not None:
        usage["cache_read_input_tokens"] = cache_read
    if cache_write is not None:
        usage["cache_creation_input_tokens"] = cache_write
    content: list[dict[str, Any]] = [{"type": "text", "text": text}] if stop != "refusal" else []
    return {"id": "msg_01", "type": "message", "role": "assistant", "model": "claude-x", "content": content,
            "stop_reason": stop, "stop_sequence": None, "usage": usage}


def openai_body(text: str | None = json.dumps(REPLY), finish: str = "stop", refusal: str | None = None,
                prompt_tokens: int = 100, completion_tokens: int = 7, cached: int | None = 40,
                cache_write: int | None = 10) -> dict[str, Any]:
    usage: dict[str, Any] = {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
                             "total_tokens": prompt_tokens + completion_tokens}
    details: dict[str, int] = {}
    if cached is not None:
        details["cached_tokens"] = cached
    if cache_write is not None:
        details["cache_write_tokens"] = cache_write
    if details:
        usage["prompt_tokens_details"] = details
    return {"id": "chatcmpl-1", "object": "chat.completion", "created": 1, "model": "gpt-x",
            "choices": [{"index": 0, "finish_reason": finish,
                         "message": {"role": "assistant", "content": text, "refusal": refusal}}], "usage": usage}


def anthropic_error(status: int, message: str = MARK) -> Answer:
    return Answer(status, {"type": "error", "error": {"type": "api_error", "message": message}})


def openai_error(status: int, message: str = MARK) -> Answer:
    return Answer(status, {"error": {"message": message, "type": "invalid_request_error", "param": None,
                                     "code": None}})


class StandIn:
    """Answers each request from its script (the last answer repeats) and keeps every request it saw."""

    def __init__(self, *script: Answer) -> None:
        self.script = list(script)
        self.requests: list[httpx.Request | httpx2.Request] = []

    def next(self) -> Answer:
        return self.script[min(len(self.requests), len(self.script)) - 1]

    @property
    def sent(self) -> list[dict[str, Any]]:
        """Each request's JSON body."""
        return [json.loads(r.content) for r in self.requests]

    @property
    def path(self) -> str:
        return self.requests[-1].url.path

    @property
    def read_timeout(self) -> float:
        return float(self.requests[-1].extensions["timeout"]["read"])

    def by_httpx(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        answer = self.next()
        if answer.raises == "timeout":
            raise httpx.ReadTimeout("timed out", request=request)
        if answer.raises == "connect":
            raise httpx.ConnectError("refused", request=request)
        if answer.raw is not None:
            return httpx.Response(answer.status, content=answer.raw, headers={"content-type": "text/html"})
        return httpx.Response(answer.status, json=answer.body)

    def by_httpx2(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        answer = self.next()
        if answer.raises == "timeout":
            raise httpx2.ReadTimeout("timed out", request=request)
        if answer.raises == "connect":
            raise httpx2.ConnectError("refused", request=request)
        if answer.raw is not None:
            return httpx2.Response(answer.status, content=answer.raw, headers={"content-type": "text/html"})
        return httpx2.Response(answer.status, json=answer.body)


def anthropic_provider(*script: Answer, name: str = "anthropic") -> tuple[AnthropicProvider, StandIn]:
    stand = StandIn(*script)
    client = AsyncAnthropic(api_key="test-key", max_retries=0,
                            http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(stand.by_httpx2)))
    return AnthropicProvider(name, client), stand


def openai_provider(*script: Answer, name: str = "openai") -> tuple[OpenAICompatibleProvider, StandIn]:
    stand = StandIn(*script)
    client = AsyncOpenAI(api_key="test-key", max_retries=0,
                         http_client=httpx.AsyncClient(transport=httpx.MockTransport(stand.by_httpx)))
    return OpenAICompatibleProvider(name, client), stand


def text_of(content: Any) -> str:
    """A message's or system prompt's text, whether the SDK sent a string or a list of text parts."""
    if isinstance(content, str):
        return content
    parts: list[dict[str, Any]] = content
    return "".join(str(part["text"]) for part in parts if part.get("type") == "text")


def system_blocks(system: Any) -> list[dict[str, Any]]:
    """The text blocks of a system prompt sent as a list; none when it was sent as a plain string."""
    if isinstance(system, str):
        return []
    blocks: list[dict[str, Any]] = system
    return blocks
