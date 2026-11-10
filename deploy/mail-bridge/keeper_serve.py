"""The keeper's control port, which the app's room login calls (`ashley.mail.proton_login_http`): `POST /login`,
`/login/verified`, `/login/two-factor`, `/login/mailbox-password` and `/forget`, JSON in and out, each carrying the epoch's token as a bearer
credential, over TLS under the certificate the pod's Secret mounts (`ashley.mail.proton_tls`). What is typed is passed to Bridge and forgotten. 401 for another token, 503 once the keeper has ended Bridge,
502 when Bridge could not be asked, 400 for a body that is not what the route takes; 200 with `step` otherwise."""

import hmac
import json
import ssl
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from keeper import Keeper
from keeper_link import BridgeError, Stopped

Route = Callable[[Keeper, dict[str, Any]], dict[str, Any]]
ROUTES: dict[str, Route] = {
    "/login": lambda k, b: k.login(_text(b, "username"), _text(b, "password")),
    "/login/verified": lambda k, b: k.verified_login(_text(b, "password")),
    "/login/two-factor": lambda k, b: k.second_factor(_text(b, "code")),
    "/login/mailbox-password": lambda k, b: k.mailbox_password(_text(b, "password")),
    "/forget": lambda k, b: k.forget(_text(b, "user_id")),
}
MAX_BODY = 16384


def _text(body: dict[str, Any], key: str) -> str:
    value = body.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(key)
    return value


def server_context(directory: str) -> ssl.SSLContext:
    """The server side of the control port's TLS: `tls.crt` and `tls.key` from `directory`."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(f"{directory}/tls.crt", f"{directory}/tls.key")
    return context


def serve(keeper: Keeper, token: str, port: int, host: str = "0.0.0.0",
          tls: ssl.SSLContext | None = None) -> ThreadingHTTPServer:
    """A server for the control port, over TLS under `tls` when given; the caller runs `serve_forever` (in a thread) and
    `shutdown`. The handshake happens in the connection's own thread, so a client that never speaks stalls only itself."""

    class Handler(BaseHTTPRequestHandler):
        timeout = 10

        def do_POST(self) -> None:
            self._answer(*_handle(keeper, token, self.path, self.headers.get("Authorization", ""),
                                  self.rfile.read(min(int(self.headers.get("Content-Length", "0")), MAX_BODY))))

        def _answer(self, status: int, body: dict[str, Any]) -> None:
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format: str, *args: Any) -> None:
            pass

    server = ThreadingHTTPServer((host, port), Handler)
    if tls is not None:
        server.socket = tls.wrap_socket(server.socket, server_side=True, do_handshake_on_connect=False)
    return server


def _handle(keeper: Keeper, token: str, path: str, authorization: str, raw: bytes) -> tuple[int, dict[str, Any]]:
    if not hmac.compare_digest(authorization.encode(), f"Bearer {token}".encode()):
        return 401, {"error": "unauthorized"}
    route = ROUTES.get(path)
    if route is None:
        return 404, {"error": "not_found"}
    try:
        body = json.loads(raw or b"{}")
        return 200, route(keeper, dict(body))
    except (ValueError, TypeError):
        return 400, {"error": "bad_request"}
    except Stopped:
        return 503, {"error": "stopped"}
    except BridgeError:
        return 502, {"error": "bridge"}
