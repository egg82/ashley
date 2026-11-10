"""One log line per request: method, route template, status, duration. The template (`/api/things/{id}`), never the
path, so an id in a URL is not logged; no query string and no client address. `/api/health` is the probe, so it is
not logged."""

import logging
import time

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .. import logs

log = logging.getLogger("ashley.api")
QUIET_ROUTES = frozenset({"/api/health"})


def route_template(scope: Scope) -> str:
    path: object = getattr(scope.get("route"), "path", None)
    return path if isinstance(path, str) else "-"


class AccessLog:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = time.perf_counter()
        status = 500

        async def capture(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, capture)
        finally:
            route = route_template(scope)
            if route not in QUIET_ROUTES:
                logs.info(log, "http.request", method=scope["method"], route=route, status=status,
                          ms=int((time.perf_counter() - started) * 1000))
