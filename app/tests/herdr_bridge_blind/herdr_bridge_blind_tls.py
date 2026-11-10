"""A real mutual-TLS bridge on an ephemeral port and a raw client for it, so the transport can be attacked."""

import json
import socket
import ssl
import threading
from collections.abc import Generator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from herdr_bridge.jsonget import obj
from herdr_bridge.server import make_server
from herdr_bridge_blind_pki import Pair, write_pair
from herdr_bridge_blind_support import PERSON, Bridge


@dataclass(frozen=True)
class Answer:
    status: int
    body: dict[str, object]
    tls_version: str


@contextmanager
def serving(b: Bridge) -> Generator[int]:
    server = make_server(b.config, b.api, b.log)
    thread = threading.Thread(target=lambda: server.serve_forever(0.01), daemon=True)
    thread.start()
    try:
        yield int(server.server_address[1])
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)


def client_context(tmp: Path, pair: Pair | None, max_version: ssl.TLSVersion | None = None) -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    if max_version is not None:
        ctx.maximum_version = max_version
    if pair is not None:
        cert, key = tmp / "c.pem", tmp / "c.key"
        write_pair(pair, cert, key)
        ctx.load_cert_chain(cert, key)
    return ctx


def parse(raw: bytes, version: str) -> Answer | None:
    if not raw.startswith(b"HTTP/"):
        return None
    head, _, body = raw.partition(b"\r\n\r\n")
    status = int(head.split(b" ", 2)[1])
    parsed: dict[str, object] = {}
    try:
        parsed = obj(json.loads(body or b"{}"))
    except ValueError:
        parsed = {"unparsed": True}
    return Answer(status, parsed, version)


def request(
    port: int,
    ctx: ssl.SSLContext | None,
    method: str,
    target: str,
    headers: Mapping[str, str],
    body: bytes = b"",
) -> Answer | None:
    """The answer, or None when the server gave no HTTP answer at all (a refused handshake, a dropped connection)."""
    lines = [f"{method} {target} HTTP/1.1", "Host: bridge", "Connection: close", f"Content-Length: {len(body)}"]
    lines += [f"{k}: {v}" for k, v in headers.items()]
    wire = ("\r\n".join(lines) + "\r\n\r\n").encode() + body
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=5) as raw:
            if ctx is None:
                raw.sendall(wire)
                return parse(_drain(raw), "none")
            with ctx.wrap_socket(raw) as tls:
                version = tls.version() or ""
                tls.sendall(wire)
                return parse(_drain(tls), version)
    except (ssl.SSLError, OSError):
        return None


def _drain(sock: socket.socket) -> bytes:
    chunks: list[bytes] = []
    try:
        while chunk := sock.recv(65536):
            chunks.append(chunk)
    except (ssl.SSLError, OSError):
        pass
    return b"".join(chunks)


def auth(b: Bridge, person: str = PERSON) -> dict[str, str]:
    return {"Authorization": f"Bearer {b.token}", "X-Ashley-Person": person}
