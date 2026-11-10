"""A stand-in for Home Assistant that answers with the bytes captured from the real one (`captured_mcp/`), and keeps
every request it saw."""

import json
from pathlib import Path
from typing import Any

import httpx2
from ashley.home_assistant.client import HomeAssistant, connect

CAPTURED = Path(__file__).parent / "captured_mcp"
MCP_PATH = "/api/mcp/assist"
TOKEN = "PLANTED-HA-TOKEN-zq"
BY_TOOL = {"llm__GetDateTime": "call-datetime", "homeassistant__GetLiveContext": "call-livecontext", "todo__get_items": "call-badargs", "no_such_tool": "call-unknown"}


def captured(name: str) -> bytes:
    return (CAPTURED / f"{name}.json").read_bytes()


def captured_json(name: str) -> Any:
    return json.loads(captured(name))


class Stand:
    """`failure` replaces the answer to every request while set: a status and body, or an exception to raise."""

    def __init__(self) -> None:
        self.requests: list[httpx2.Request] = []
        self.failure: tuple[int, bytes] | Exception | None = None
        self.states: dict[str, str] = {}

    def methods(self) -> list[str]:
        return [str(json.loads(r.content)["method"]) for r in self.requests if r.url.path == MCP_PATH]

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        if isinstance(self.failure, Exception):
            raise self.failure
        if self.failure is not None:
            return httpx2.Response(self.failure[0], content=self.failure[1])
        if request.url.path.startswith("/api/states/"):
            entity = request.url.path.removeprefix("/api/states/")
            if entity not in self.states:
                return httpx2.Response(404, content=captured("state-missing"))
            return httpx2.Response(200, json={"entity_id": entity, "state": self.states[entity], "attributes": {}})
        if request.url.path != MCP_PATH:
            return httpx2.Response(404, content=b"404: Not Found")
        body = json.loads(request.content)
        if request.headers.get("Authorization") != f"Bearer {TOKEN}":
            return httpx2.Response(401, content=captured("unauth"))
        method = body["method"]
        if method == "initialize":
            return httpx2.Response(200, content=captured("initialize"))
        if method == "tools/list":
            return httpx2.Response(200, content=captured("tools-list"))
        return httpx2.Response(200, content=captured(BY_TOOL.get(body["params"]["name"], "call-unknown")))

    def home_assistant(self) -> HomeAssistant:
        real = connect("http://ha.test:8123", TOKEN)
        return HomeAssistant(httpx2.AsyncClient(
            base_url=real.http.base_url, headers=real.http.headers, transport=httpx2.MockTransport(self.handle)))
