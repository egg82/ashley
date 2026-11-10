"""What the search sources (`web_search`, `places`) share: one tool taking one `query`, a GET whose failure is the
source not answering, and the `tools.call` line, which carries the outcome, the result count and the duration, never
the query, a URL or a result."""

import json
import logging
import time
from collections.abc import Mapping

import httpx2

from .. import logs
from ..inference.model import ToolCall, ToolResult, ToolSpec

log = logging.getLogger("ashley.tools")

QUERY: Mapping[str, object] = {
    "type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}


class NoAnswer(Exception):
    """The source timed out, could not be reached, answered an error status or a body that is not what it serves."""


def spec(name: str, description: str) -> ToolSpec:
    return ToolSpec(name, description, QUERY, outside=True, tier="runs")


def query(call: ToolCall) -> str | None:
    """The call's `query`, stripped; None when it is missing, not a string or blank."""
    value = call.arguments.get("query")
    return (value.strip() or None) if isinstance(value, str) else None


async def get(http: httpx2.AsyncClient, url: str, params: Mapping[str, str | int | float], timeout_s: float) -> bytes:
    """The body of a successful GET. Raises NoAnswer."""
    try:
        response = await http.get(url, params=dict(params), timeout=timeout_s)
    except httpx2.HTTPError as e:
        raise NoAnswer() from e
    if not response.is_success:
        raise NoAnswer()
    return response.content


def ok(call: ToolCall, started: float, body: object, count: int) -> ToolResult:
    return done(call, "ok", started, ToolResult(call.id, json.dumps(body, ensure_ascii=False)), count)


def failed(call: ToolCall, outcome: str, started: float, reason: str) -> ToolResult:
    return done(call, outcome, started, ToolResult(call.id, reason, is_error=True), 0)


def done(call: ToolCall, outcome: str, started: float, result: ToolResult, count: int) -> ToolResult:
    logs.info(log, "tools.call", tool=call.name, outcome=outcome, results=count,
              duration_ms=int((time.monotonic() - started) * 1000))
    return result


def unknown(call: ToolCall, started: float) -> ToolResult:
    return failed(call, "unknown_tool", started, f"no tool named {call.name}")
