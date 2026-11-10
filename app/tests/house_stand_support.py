"""A small Home Assistant for the House adapter's tests: a real HTTP and WebSocket server on a local port (uvicorn in a
thread), serving the REST paths and WebSocket commands `ha_house.HaHouse` uses from a dict world, and recording every
call with the bearer token it came with. It speaks HA's shapes as read from a 2026.10.4 container; it is not HA."""

import logging
import socket
import threading
from collections.abc import Generator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect

TOKEN = "stand-token-zq"


@dataclass
class Stand:
    """The world: `states`, the registries as lists of rows, `entries` (config entries), `aliases` per entity id, helper
    lists per type, `automations` and `scripts` configs by id, `services` (the catalogue). `calls` is every request as
    (kind, what, bearer): `("rest", "GET /api/states", token)` or `("ws", "config/area_registry/list", token)`."""

    states: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    registries: dict[str, list[dict[str, Any]]] = field(default_factory=dict[str, list[dict[str, Any]]])
    entries: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    aliases: dict[str, list[str | None]] = field(default_factory=dict[str, list[str | None]])
    helpers: dict[str, list[dict[str, Any]]] = field(default_factory=dict[str, list[dict[str, Any]]])
    automations: dict[str, dict[str, Any]] = field(default_factory=dict[str, dict[str, Any]])
    scripts: dict[str, dict[str, Any]] = field(default_factory=dict[str, dict[str, Any]])
    services: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    diagnostics: dict[str, dict[str, Any]] = field(default_factory=dict[str, dict[str, Any]])
    calls: list[tuple[str, str, str]] = field(default_factory=list[tuple[str, str, str]])
    commands: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    posted: list[tuple[str, Any, dict[str, str]]] = field(default_factory=list[tuple[str, Any, dict[str, str]]])
    reject: str | None = None
    token: str = TOKEN

    # ---- REST
    def _note(self, request: Request) -> None:
        self.calls.append(("rest", f"{request.method} {request.url.path}", request.headers.get("authorization", "")))

    def _allowed(self, request: Request) -> bool:
        return request.headers.get("authorization") == f"Bearer {self.token}"

    async def rest(self, request: Request) -> Response:
        self._note(request)
        if not self._allowed(request):
            return JSONResponse({"message": "401: Unauthorized"}, status_code=401)
        path = request.url.path
        for kind, store in (("automation", self.automations), ("script", self.scripts)):
            prefix = f"/api/config/{kind}/config/"
            if path.startswith(prefix):
                return await self._config(request, store, path.removeprefix(prefix))
        if path == "/api/states":
            return JSONResponse(self.states)
        if path == "/api/services" and request.method == "GET":
            return JSONResponse(self.services)
        if path.startswith("/api/services/"):
            return await self._service(request, path.removeprefix("/api/services/"))
        if path.startswith("/api/history/period/"):
            wanted = request.query_params.get("filter_entity_id", "").split(",")
            return JSONResponse([[{"entity_id": s["entity_id"], "state": s["state"],
                                   "last_changed": "2026-11-01T11:00:00+00:00"}] for s in self.states if s["entity_id"] in wanted])
        if path.startswith("/api/logbook/"):
            return JSONResponse([{"when": "2026-11-01T11:30:00+00:00", "name": "Porch", "message": "turned on",
                                  "entity_id": request.query_params.get("entity")}])
        if path.startswith("/api/diagnostics/config_entry/"):
            found = self.diagnostics.get(path.rsplit("/", 1)[1])
            return JSONResponse(found) if found is not None else JSONResponse({}, status_code=404)
        if path.startswith("/api/config/config_entries/entry/") and request.method == "DELETE":
            self.entries = [e for e in self.entries if e["entry_id"] != path.rsplit("/", 1)[1]]
            return JSONResponse({"require_restart": False})
        return JSONResponse({}, status_code=404)

    async def _config(self, request: Request, store: dict[str, dict[str, Any]], config_id: str) -> Response:
        if request.method == "GET":
            return JSONResponse(store[config_id]) if config_id in store else JSONResponse({}, status_code=404)
        if self.reject is not None:
            return JSONResponse({"message": self.reject}, status_code=400)
        if request.method == "DELETE":
            return JSONResponse({"result": "ok"}) if store.pop(config_id, None) is not None else JSONResponse({}, status_code=404)
        store[config_id] = {"id": config_id, **await request.json()}
        return JSONResponse({"result": "ok"})

    async def _service(self, request: Request, name: str) -> Response:
        body = await request.json()
        self.posted.append((name, body, dict(request.query_params)))
        only = any(f"{d['domain']}/{s}" == name for d in self.services for s, spec in d["services"].items()
                   if isinstance(spec.get("response"), dict) and not spec["response"].get("optional"))
        asked = "return_response" in request.query_params
        if only and not asked:
            return JSONResponse({"message": "Action requires responses but caller did not ask for responses"}, status_code=400)
        if self.reject is not None:
            return JSONResponse({"message": self.reject}, status_code=400)
        changed = [s for s in self.states if s["entity_id"] in (body.get("entity_id") or [])]
        if asked:
            return JSONResponse({"changed_states": [], "service_response": {"answer": 42}})
        return JSONResponse(changed)

    # ---- WebSocket
    async def socket(self, ws: WebSocket) -> None:
        await ws.accept()
        await ws.send_json({"type": "auth_required"})
        auth = await ws.receive_json()
        self.calls.append(("ws", "auth", f"Bearer {auth.get('access_token')}"))
        if auth.get("access_token") != self.token:
            await ws.send_json({"type": "auth_invalid"})
            return
        await ws.send_json({"type": "auth_ok"})
        try:
            command = await ws.receive_json()
        except WebSocketDisconnect:
            return
        self.commands.append(command)
        self.calls.append(("ws", command["type"], f"Bearer {auth['access_token']}"))
        await ws.send_json({"id": command["id"], "type": "result", **self._answer(command)})

    def _answer(self, command: Mapping[str, Any]) -> dict[str, Any]:
        kind = str(command["type"])
        if self.reject is not None and not kind.endswith("/list") and kind != "config/entity_registry/get_entries":
            return {"success": False, "error": {"code": "home_assistant_error", "message": self.reject}}
        if kind.endswith("_registry/list"):
            return {"success": True, "result": self.registries.get(kind.split("/")[1].removesuffix("_registry"), [])}
        if kind == "config_entries/get":
            return {"success": True, "result": self.entries}
        if kind == "config/entity_registry/get_entries":
            return {"success": True, "result": {i: {"aliases": self.aliases.get(i, [])} for i in command["entity_ids"]}}
        domain, _, verb = kind.partition("/")
        if domain in self.helpers or verb in ("list", "create"):
            return self._helper(domain, verb, command)
        return {"success": True, "result": None}

    def _helper(self, domain: str, verb: str, command: Mapping[str, Any]) -> dict[str, Any]:
        items = self.helpers.setdefault(domain, [])
        if verb == "list":
            return {"success": True, "result": items}
        if verb == "create":
            made = {"id": str(command["name"]).lower().replace(" ", "_"), "name": command["name"]}
            items.append(made)
            return {"success": True, "result": made}
        if verb == "delete":
            self.helpers[domain] = [i for i in items if i["id"] != command.get(f"{domain}_id")]
        return {"success": True, "result": None}

    def app(self) -> Starlette:
        return Starlette(routes=[WebSocketRoute("/api/websocket", self.socket),
                                 Route("/{path:path}", self.rest, methods=["GET", "POST", "DELETE"])])


@contextmanager
def serving(stand: Stand) -> Generator[str]:
    """The stand listening on a free local port for the block; its base URL."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    loggers = [logging.getLogger(n) for n in ("uvicorn", "uvicorn.error", "uvicorn.access")]
    levels = [lg.level for lg in loggers]
    server = uvicorn.Server(uvicorn.Config(stand.app(), log_config=None, log_level="critical"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    while not server.started:
        thread.join(0.01)
    try:
        yield f"http://127.0.0.1:{sock.getsockname()[1]}"
    finally:
        server.should_exit = True
        thread.join(5)
        for lg, level in zip(loggers, levels, strict=True):
            lg.setLevel(level)
