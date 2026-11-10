"""The HTTPS server: TLS 1.3 with a client certificate required, handing each request to the Api."""

import json
import ssl
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl, urlsplit

from .api import MAX_BODY, Api, Request
from .config import Config
from .logs import Log

SOCKET_TIMEOUT_S = 30


def tls_context(config: Config) -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_3
    ctx.load_cert_chain(config.cert, config.key)
    ctx.load_verify_locations(config.client_ca)
    ctx.verify_mode = ssl.CERT_REQUIRED
    return ctx


class Server(ThreadingHTTPServer):
    log: Log

    def handle_error(self, request: object, client_address: object) -> None:
        """A failed handshake or a dropped connection: one line, never the client's address."""
        kind = sys.exc_info()[0]
        self.log.emit(f"call=connection status=failed error={kind.__name__ if kind else '-'}")


def make_server(config: Config, api: Api, log: Log) -> Server:
    class Handler(BaseHTTPRequestHandler):
        timeout = SOCKET_TIMEOUT_S

        def setup(self) -> None:
            if isinstance(self.request, ssl.SSLSocket):
                self.request.settimeout(SOCKET_TIMEOUT_S)
                self.request.do_handshake()
            super().setup()

        def serve(self) -> None:
            url = urlsplit(self.path)
            length = int(self.headers.get("Content-Length") or 0)
            limit = config.max_file_bytes if self.command == "PUT" else MAX_BODY
            body = self.rfile.read(length if length <= limit else limit + 1 if self.command != "PUT" else 0)
            if length > len(body):
                self.close_connection = True  # the rest of an over-long body is never read
            headers = {k.lower(): v for k, v in self.headers.items()}
            res = api.handle(Request(self.command, url.path, dict(parse_qsl(url.query)), headers, body))
            payload = json.dumps(res.body).encode() if res.raw is None else res.raw
            self.send_response(res.status)
            self.send_header("Content-Type", "application/json" if res.raw is None else "application/octet-stream")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        do_GET = serve
        do_POST = serve
        do_PUT = serve

        def log_message(self, format: str, *args: object) -> None:
            return

    server = Server((config.host, config.port), Handler)
    server.log = log
    server.socket = tls_context(config).wrap_socket(server.socket, server_side=True, do_handshake_on_connect=False)
    return server
