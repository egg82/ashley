"""One log line per request for the `web` Deployment: method, path, status, bytes, duration_ms. The path is the URL's
path alone: no query string, no headers, no cookies, no client address. Kubelet probes (`kube-probe/` user agent) and
`/api/health` are not logged."""

import logging
import time

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .. import logs

log = logging.getLogger("ashley.web")
_PROBE_AGENT = b"kube-probe/"
_QUIET_PATHS = frozenset({"/api/health"})


def _is_probe(scope: Scope) -> bool:
    if scope["path"] in _QUIET_PATHS:
        return True
    return any(k == b"user-agent" and v.startswith(_PROBE_AGENT) for k, v in scope["headers"])


class WebAccessLog:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or _is_probe(scope):
            await self.app(scope, receive, send)
            return
        started = time.perf_counter()
        status = 500
        sent = 0

        async def capture(message: Message) -> None:
            nonlocal status, sent
            if message["type"] == "http.response.start":
                status = message["status"]
            elif message["type"] == "http.response.body":
                sent += len(message.get("body", b""))
            await send(message)

        try:
            await self.app(scope, receive, capture)
        finally:
            logs.info(log, "web.request", method=scope["method"], path=scope["path"], status=status, bytes=sent,
                      duration_ms=int((time.perf_counter() - started) * 1000))
