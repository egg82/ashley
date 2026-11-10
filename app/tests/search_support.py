"""Helpers for the search sources' tests: the captured SearXNG and Photon answers (`search_captures/`, recorded
2026-10-27; Photon's around the round point 40.0, -105.0), served by an in-process `httpx2` transport that records
each request, and the shipped config."""

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx2

from ashley.inference.model import ToolCall
from ashley.tools import search_config

CAPTURES = Path(__file__).parent / "search_captures"
CONFIG = search_config.load()
SEARXNG_URL = "https://search.test"


def captured(name: str) -> Any:
    return json.loads((CAPTURES / f"{name}.json").read_text())


@dataclass
class Fake:
    """Answers every request with `answer(request)`; `requests` is what was asked, in order."""

    answer: Callable[[httpx2.Request], httpx2.Response]
    requests: list[httpx2.Request] = field(default_factory=list[httpx2.Request])

    def client(self, headers: dict[str, str] | None = None) -> httpx2.AsyncClient:
        def handle(request: httpx2.Request) -> httpx2.Response:
            self.requests.append(request)
            return self.answer(request)
        return httpx2.AsyncClient(transport=httpx2.MockTransport(handle), headers=headers)


def serving(body: Any, status: int = 200) -> Fake:
    return Fake(lambda _: httpx2.Response(status, json=body))


def raising(error: Exception) -> Fake:
    def answer(request: httpx2.Request) -> httpx2.Response:
        raise error
    return Fake(answer)


def call(name: str, **arguments: object) -> ToolCall:
    return ToolCall("c1", name, arguments)


def events(out: str, event: str) -> list[dict[str, str]]:
    """The logfmt lines for `event`, as field maps (values unquoted; enough for ids, counts and outcomes)."""
    found: list[dict[str, str]] = []
    for line in out.splitlines():
        fields = dict(part.split("=", 1) for part in line.split(" ") if "=" in part)
        if fields.get("event") == event:
            found.append(fields)
    return found
