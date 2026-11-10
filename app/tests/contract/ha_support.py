"""Helpers for the blind Home Assistant tests: an in-process `httpx2` transport replaying captured real HA responses
(`ha_captures/`, recorded from HA 2026.10's `mcp_server` with people's names replaced), and the `HomeAssistant` handle
built over it the way `connect` documents (base URL plus bearer header).

The MCP endpoint is `/api/mcp/assist` (the Assist API's own endpoint; the all-APIs one needs an admin user). Replayed
JSON-RPC responses carry the request's own `id`, as HA's do. A notification (no `id`) is answered 202 with no body, as
the MCP streamable-HTTP transport specifies. A request that honours its own read timeout gets `ReadTimeout` once that
passes when the transport is told to hang, as a real socket would."""

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import httpx2
from ashley.home_assistant.client import HomeAssistant

CAPTURES = Path(__file__).parent / "ha_captures"
MCP_PATH = "/api/mcp/assist"
HA_TOKEN = "zqHATOKEN-55aa66bb"
LIVE_CONTEXT = "homeassistant__GetLiveContext"
Fault = Literal["unauthorized", "connect", "hang", "not_json", "rpc_error", "server_error", "no_result"]


def capture(name: str) -> Any:
    return json.loads((CAPTURES / name).read_text())


TOOLS = capture("tools-list.json")["result"]["tools"]


def reply(status: int, body: Any = None, text: str | None = None) -> httpx2.Response:
    if text is not None:
        return httpx2.Response(status, text=text, headers={"Content-Type": "text/plain; charset=utf-8"})
    return httpx2.Response(status, json=body)


async def hang(request: httpx2.Request) -> httpx2.Response:
    timeout: dict[str, float | None] = request.extensions.get("timeout", {})
    read = timeout.get("read")
    await asyncio.sleep(read if read is not None else 30.0)
    raise httpx2.ReadTimeout("timed out", request=request)


@dataclass
class ReplayHA:
    """`faults` maps an MCP method (or `tools/call:<name>`, or a state's entity id) to how it fails; `once` makes each
    fault fire one time only. `states` are the person entities HA knows."""

    faults: dict[str, Fault] = field(default_factory=dict[str, Fault])
    once: bool = False
    states: dict[str, str] = field(default_factory=dict[str, str])
    mcp: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    gets: list[str] = field(default_factory=list[str])
    auth: list[str | None] = field(default_factory=list[str | None])

    def handle(self, request: httpx2.Request) -> Any:
        self.auth.append(request.headers.get("Authorization"))
        if request.method == "POST" and request.url.path == MCP_PATH:
            return self._mcp(request)
        if request.method == "GET" and request.url.path.startswith("/api/states/"):
            return self._state(request, request.url.path.removeprefix("/api/states/"))
        return reply(404, {"message": "Not found"})

    def _fault(self, key: str) -> Fault | None:
        found = self.faults.get(key)
        if found is not None and self.once:
            del self.faults[key]
        return found

    def _mcp(self, request: httpx2.Request) -> Any:
        body: dict[str, Any] = json.loads(request.content)
        self.mcp.append(body)
        if "id" not in body:
            return httpx2.Response(202)
        method = str(body.get("method"))
        key = f"tools/call:{body['params']['name']}" if method == "tools/call" else method
        fault = self._fault(key) or self._fault(method)
        if fault is not None:
            return self._failing(request, fault, body["id"])
        found = self._answer(method, body)
        found["id"] = body["id"]
        return reply(200, found)

    def _answer(self, method: str, body: dict[str, Any]) -> dict[str, Any]:
        if method == "initialize":
            return capture("initialize.json")
        if method == "tools/list":
            return capture("tools-list.json")
        if method == "tools/call":
            name = body["params"]["name"]
            if name not in {t["name"] for t in TOOLS}:
                return capture("call-unknown.json")
            if name == LIVE_CONTEXT:
                return capture("call-livecontext.json")
            return capture("call-badargs.json" if name == "todo__get_items" else "call-datetime.json")
        return {"jsonrpc": "2.0", "error": {"code": -32601, "message": "Method not found"}}

    def _failing(self, request: httpx2.Request, fault: Fault, rpc_id: Any) -> Any:
        if fault == "unauthorized":
            return reply(401, text=(CAPTURES / "unauth.json").read_text())
        if fault == "connect":
            raise httpx2.ConnectError("connection refused", request=request)
        if fault == "hang":
            return hang(request)
        if fault == "not_json":
            return reply(200, text="<html>bad gateway</html>")
        if fault == "server_error":
            return reply(500, text="500 Internal Server Error")
        if fault == "no_result":
            return reply(200, {"jsonrpc": "2.0", "id": rpc_id})
        return reply(200, {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": -32603, "message": "internal"}})

    def _state(self, request: httpx2.Request, entity: str) -> Any:
        self.gets.append(entity)
        fault = self._fault(entity)
        if fault is not None:
            return self._failing(request, fault, None)
        if entity not in self.states:
            return reply(404, capture("state-missing.json"))
        return reply(200, {"entity_id": entity, "state": self.states[entity],
                           "attributes": {"friendly_name": "Someone", "source": "device_tracker.phone"},
                           "last_changed": "2026-10-25T18:00:00+00:00", "last_reported": "2026-10-25T18:00:00+00:00",
                           "last_updated": "2026-10-25T18:00:00+00:00",
                           "context": {"id": "01JZ", "parent_id": None, "user_id": None}})

    def methods(self) -> list[str]:
        return [str(m.get("method")) for m in self.mcp]

    def handle_for(self) -> HomeAssistant:
        transport = httpx2.MockTransport(self.handle)
        return HomeAssistant(httpx2.AsyncClient(transport=transport, base_url="http://ha.test:8123",
                                                headers={"Authorization": f"Bearer {HA_TOKEN}"}))
