"""Stand-in Responses API answers for `OpenAIResponsesProvider`, shaped after OpenAI's API reference for `POST
/v1/responses` (not captured from a live call), and a provider whose real SDK client talks to them."""

import json
from typing import Any

import httpx
from ashley.inference.providers import OpenAIResponsesProvider
from inference_wire_support import REPLY, Answer, StandIn
from openai import AsyncOpenAI


def responses_body(text: str | None = json.dumps(REPLY), status: str = "completed", incomplete: str | None = None,
                   refusal: str | None = None, input_tokens: int = 100, output_tokens: int = 7, cached: int = 40,
                   cache_write: int = 10, calls: tuple[tuple[str, str, str], ...] = (), error_code: str | None = None,
                   reasoning: bool = False) -> dict[str, Any]:
    """A response object: `calls` are (call_id, name, arguments-as-the-JSON-string) `function_call` items."""
    output: list[dict[str, Any]] = []
    if reasoning:
        output.append({"id": "rs_1", "type": "reasoning", "summary": []})
    if text is not None or refusal is not None:
        part: dict[str, Any] = ({"type": "refusal", "refusal": refusal} if refusal is not None
                                else {"type": "output_text", "text": text, "annotations": []})
        output.append({"id": "msg_1", "type": "message", "role": "assistant", "status": "completed", "content": [part]})
    output.extend({"id": f"fc_{i}", "type": "function_call", "call_id": i, "name": n, "arguments": a,
                   "status": "completed"} for i, n, a in calls)
    return {"id": "resp_1", "object": "response", "created_at": 1, "model": "gpt-x", "status": status,
            "error": {"code": error_code, "message": "x"} if error_code else None,
            "incomplete_details": {"reason": incomplete} if incomplete else None, "output": output,
            "parallel_tool_calls": True, "tool_choice": "auto", "tools": [],
            "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens,
                      "total_tokens": input_tokens + output_tokens,
                      "input_tokens_details": {"cached_tokens": cached, "cache_write_tokens": cache_write},
                      "output_tokens_details": {"reasoning_tokens": 3}}}


def responses_provider(*script: Answer, name: str = "openai") -> tuple[OpenAIResponsesProvider, StandIn]:
    stand = StandIn(*script)
    client = AsyncOpenAI(api_key="test-key", max_retries=0,
                         http_client=httpx.AsyncClient(transport=httpx.MockTransport(stand.by_httpx)))
    return OpenAIResponsesProvider(name, client), stand
