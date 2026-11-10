"""The stand-in's REST half: Home Assistant's `/api/` endpoints over an `Ha`."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from hag_state_support import Ha, Json
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route


def stamp(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)


class RestApi:
    def __init__(self, ha: Ha) -> None:
        self.ha = ha

    def denied(self, request: Request) -> Response | None:
        if request.headers.get("authorization") != f"Bearer {self.ha.token}":
            return JSONResponse({"message": "401: Unauthorized"}, status_code=401)
        if self.ha.status is not None:
            return JSONResponse({"message": "broken"}, status_code=self.ha.status)
        if self.ha.garbage:
            return Response("<html>not json</html>", media_type="text/html")
        return None

    def wrap(self, handler: Callable[..., Any]) -> Callable[[Request], Any]:
        async def wrapped(request: Request) -> Response:
            body: Any = None
            if request.method == "POST":
                raw = await request.body()
                body = await request.json() if raw else {}
            self.ha.requests.append((request.method, request.url.path, dict(request.query_params), body))
            return self.denied(request) or handler(request, body)
        return wrapped

    def routes(self) -> list[Route]:
        w = self.wrap
        return [
            Route("/api/", w(self.root)), Route("/api/states", w(self.all_states)),
            Route("/api/states/{entity_id}", w(self.one_state)), Route("/api/history/period/{ts}", w(self.history)),
            Route("/api/logbook/{ts}", w(self.logbook)), Route("/api/services", w(self.services)),
            Route("/api/services/{domain}/{service}", w(self.call), methods=["POST"]),
            Route("/api/config/{kind}/config/{config_id}", w(self.config_file), methods=["GET", "POST", "DELETE"]),
            Route("/api/config/config_entries/entry", w(self.entries)),
            Route("/api/config/config_entries/entry/{entry_id}", w(self.remove_entry), methods=["DELETE"]),
            Route("/api/diagnostics/config_entry/{entry_id}", w(self.diagnostics)),
        ]

    def root(self, _: Request, __: Any) -> Response:
        return JSONResponse({"message": "API running."})

    def all_states(self, _: Request, __: Any) -> Response:
        return JSONResponse(list(self.ha.states.values()))

    def one_state(self, request: Request, _: Any) -> Response:
        got = self.ha.states.get(request.path_params["entity_id"])
        return JSONResponse(got) if got else JSONResponse({"message": "Entity not found."}, status_code=404)

    def history(self, request: Request, _: Any) -> Response:
        start = stamp(request.path_params["ts"])
        end = stamp(request.query_params["end_time"]) if "end_time" in request.query_params else start + timedelta(days=1)
        wanted = [i for i in request.query_params.get("filter_entity_id", "").split(",") if i] or list(self.ha.history)
        out: list[list[Json]] = []
        for i in wanted:
            rows = sorted(self.ha.history.get(i, []))
            before = [r for r in rows if r[0] < start]
            inside = [r for r in rows if start <= r[0] <= end]
            if before:
                inside.insert(0, (start, before[-1][1]))
            if inside:
                out.append([{"entity_id": i, "state": s, "attributes": {}, "last_changed": t.isoformat(),
                             "last_updated": t.isoformat()} for t, s in inside])
        return JSONResponse(out)

    def logbook(self, request: Request, _: Any) -> Response:
        start = stamp(request.path_params["ts"])
        end = stamp(request.query_params["end_time"]) if "end_time" in request.query_params else start + timedelta(days=1)
        only = request.query_params.get("entity")
        rows = [r for r in self.ha.logbook if start <= stamp(r["when"]) <= end and (only is None or r.get("entity_id") == only)]
        return JSONResponse(rows)

    def services(self, _: Request, __: Any) -> Response:
        return JSONResponse([{"domain": d, "services": s} for d, s in self.ha.services.items()])

    def call(self, request: Request, body: Any) -> Response:
        domain, name = request.path_params["domain"], request.path_params["service"]
        if self.ha.reject_calls:
            return JSONResponse({"message": "refused-marker"}, status_code=400)
        found = self.ha.services.get(domain, {}).get(name)
        if found is None:
            return JSONResponse({"message": f"Service {domain}.{name} not found."}, status_code=400)
        asked = "return_response" in request.query_params
        mode = found.get("response")
        if mode is not None and not mode["optional"] and not asked:
            return JSONResponse({"message": "Service call requires responses but caller did not ask for responses"}, status_code=400)
        if mode is None and asked:
            return JSONResponse({"message": "Service does not support responses"}, status_code=400)
        changed = self.ha.effects.get(f"{domain}.{name}", lambda _h, _d: [])(self.ha, body)
        states = [self.ha.states[i] for i in changed]
        if asked:
            return JSONResponse({"changed_states": states, "service_response": self.ha.responses.get(f"{domain}.{name}", {})})
        return JSONResponse(states)

    def config_file(self, request: Request, body: Any) -> Response:
        kind, config_id = request.path_params["kind"], request.path_params["config_id"]
        held = self.ha.configs[kind]
        if request.method == "GET":
            return JSONResponse(held[config_id]) if config_id in held else JSONResponse({"message": "Resource not found"}, status_code=404)
        if request.method == "DELETE":
            if config_id not in held:
                return JSONResponse({"message": "Resource not found"}, status_code=404)
            self.ha.drop_config(kind, config_id)
            return JSONResponse({"result": "ok"})
        config: Json = body
        if "alias" not in config:
            return JSONResponse({"message": "Message malformed: required key not provided @ data['alias']"}, status_code=400)
        self.ha.put_config(kind, config_id, config)
        return JSONResponse({"result": "ok"})

    def entries(self, _: Request, __: Any) -> Response:
        return JSONResponse(list(self.ha.entries.values()))

    def remove_entry(self, request: Request, _: Any) -> Response:
        entry_id = request.path_params["entry_id"]
        if entry_id not in self.ha.entries:
            return JSONResponse({"message": "Invalid entry specified"}, status_code=404)
        del self.ha.entries[entry_id]
        return JSONResponse({"require_restart": False})

    def diagnostics(self, request: Request, _: Any) -> Response:
        got = self.ha.diagnostics.get(request.path_params["entry_id"])
        return JSONResponse(got) if got is not None else JSONResponse({"message": "Diagnostics not found"}, status_code=404)
