"""Helpers for the blind search tests: the shipped config values, captured SearXNG and Photon bodies
(`search_searxng_dst.json`, `search_photon_target.json`, real output trimmed; the Photon query was made with the round
coordinates 40.0/-105.0), an `httpx2.MockTransport` that records each request, a stub `Tools` source, and an
independent great-circle distance (miles) to check the places ranking against.

The zone.home body is NOT captured (no token for HA here); it is shaped from HA's documented state object."""

import asyncio
import json
import math
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import httpx2
from ashley.inference.model import ToolCall, ToolResult, ToolSpec
from ashley.tools.search_config import SearchConfig
from ashley.tools.tools import Catalogue, Tools, ToolsUnavailable

HERE = Path(__file__).parent
SEARXNG_URL = "https://searx.test"
CONFIG = SearchConfig(photon_url="https://photon.test", timeout_s=3, web_results=5,
                      snippet_chars=300, places_fetched=15, places_results=3, bias_decimals=2, home_ttl_s=10)
SEARXNG: dict[str, Any] = json.loads((HERE / "search_searxng_dst.json").read_text())
PHOTON: dict[str, Any] = json.loads((HERE / "search_photon_target.json").read_text())
MARK = "zqQUERY9137"
"""A query text that must never reach a log line or an error reason."""


def cfg(**changes: Any) -> SearchConfig:
    return replace(CONFIG, **changes)


def run[R](scenario: Coroutine[Any, Any, R], limit: float = 20.0) -> R:
    async def bounded() -> R:
        return await asyncio.wait_for(scenario, limit)

    return asyncio.run(bounded())


def miles(a_lat: float, a_lon: float, b_lat: float, b_lon: float) -> float:
    p, q = math.radians(a_lat), math.radians(b_lat)
    h = math.sin((q - p) / 2) ** 2 + math.cos(p) * math.cos(q) * math.sin(math.radians(b_lon - a_lon) / 2) ** 2
    return 2 * 3958.8 * math.asin(math.sqrt(h))


@dataclass
class Web:
    """A fake internet: answers every request with `answer` (a response, or a callable making one or raising), and
    keeps the requests."""

    answer: httpx2.Response | Callable[[httpx2.Request], httpx2.Response] = field(
        default_factory=lambda: httpx2.Response(200, json={}))
    requests: list[httpx2.Request] = field(default_factory=list[httpx2.Request])

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        return self.answer(request) if callable(self.answer) else self.answer

    def client(self) -> httpx2.AsyncClient:
        return httpx2.AsyncClient(transport=httpx2.MockTransport(self.handle))


def json_web(body: Any, status: int = 200) -> Web:
    return Web(httpx2.Response(status, json=body))


def failing_web(error: Exception) -> Web:
    def raise_it(request: httpx2.Request) -> httpx2.Response:
        raise error

    return Web(raise_it)


def timeout_web() -> Web:
    return failing_web(httpx2.ReadTimeout("timed out"))


def connect_web() -> Web:
    return failing_web(httpx2.ConnectError("refused"))


BROKEN_BODIES: dict[str, httpx2.Response] = {
    "server_error": httpx2.Response(500, text="500 Internal Server Error"),
    "not_found": httpx2.Response(404, json={"results": []}),
    "rate_limited": httpx2.Response(429, text="Too Many Requests"),
    "html": httpx2.Response(200, text="<html>bad gateway</html>"),
    "json_list": httpx2.Response(200, json=[]),
    "json_without_results": httpx2.Response(200, json={"query": "x"}),
    "results_not_a_list": httpx2.Response(200, json={"results": "none"}),
}


def call(name: str, arguments: dict[str, object], call_id: str = "c1") -> ToolCall:
    return ToolCall(call_id, name, arguments)


def spec(name: str) -> ToolSpec:
    return ToolSpec(name, f"does {name}", {"type": "object", "properties": {}})


@dataclass
class Stub(Tools):
    """A tools source offering `names`; `down` makes its catalogue raise; `gate` runs inside `catalogue` (to prove
    concurrency); results are `f"{label}:{name}"`."""

    label: str
    names: tuple[str, ...] = ()
    instructions: str | None = None
    down: bool = False
    gate: Callable[[], Coroutine[Any, Any, None]] | None = None
    catalogues: int = 0
    called: list[ToolCall] = field(default_factory=list[ToolCall])

    async def catalogue(self) -> Catalogue:
        self.catalogues += 1
        if self.gate:
            await self.gate()
        if self.down:
            raise ToolsUnavailable(f"{self.label} is down")
        return Catalogue(tuple(spec(n) for n in self.names), self.instructions)

    async def call(self, call: ToolCall) -> ToolResult:
        self.called.append(call)
        return ToolResult(call.id, f"{self.label}:{call.name}")
