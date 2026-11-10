"""One HTTPS exchange with a bridge over mutual TLS, blocking (the adapter runs it in a thread). The bridge's own
certificate is self-signed, so nothing is verified by a CA or a name: the connection is made, the certificate the
bridge presents is compared with the pinned fingerprint, and only then is the request, token included, sent."""

import hashlib
import hmac
import http.client
import ssl
from dataclasses import dataclass
from urllib.parse import urlsplit

from .model import Access, BridgeFailed

TLS_FAILURES = (OSError, http.client.HTTPException)


@dataclass(frozen=True)
class ClientCertificate:
    cert_file: str
    key_file: str


@dataclass(frozen=True)
class Request:
    method: str
    path: str
    body: bytes | None = None
    changes: bool = False
    """A change that was sent and not answered may have happened: `unconfirmed`, where a read is `herdr_unavailable`."""
    binary: bool = False
    """The body is a file's raw bytes and not JSON."""


def _context(certificate: ClientCertificate) -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE  # the pin below replaces CA and name verification
    ctx.minimum_version = ssl.TLSVersion.TLSv1_3
    ctx.load_cert_chain(certificate.cert_file, certificate.key_file)
    return ctx


def exchange(access: Access, certificate: ClientCertificate, request: Request, timeout_s: float,
             max_bytes: int) -> tuple[int, bytes]:
    """(status, body) of the bridge's answer. Raises BridgeFailed: `herdr_unavailable` when nothing reached the bridge,
    or a read got no answer; `pin_mismatch` when the certificate is not the pinned one (nothing sent); `unconfirmed`
    when a change was sent and got no answer; `unexpected` for an answer over `max_bytes`."""
    parts = urlsplit(access.origin)
    try:
        conn = http.client.HTTPSConnection(parts.hostname or "", parts.port, context=_context(certificate),
                                           timeout=timeout_s)
        conn.connect()
    except TLS_FAILURES as e:
        raise BridgeFailed("herdr_unavailable") from e
    try:
        _pinned(conn, access.fingerprint)
        headers = {"Authorization": f"Bearer {access.token}", "X-Ashley-Person": str(access.person),
                   "Accept": "application/json"}
        if request.body is not None:
            headers["Content-Type"] = "application/octet-stream" if request.binary else "application/json"
        try:
            conn.request(request.method, parts.path.rstrip("/") + request.path, request.body, headers)
            res = conn.getresponse()
            body = res.read(max_bytes + 1)
        except TLS_FAILURES as e:
            raise BridgeFailed("unconfirmed" if request.changes else "herdr_unavailable") from e
        if len(body) > max_bytes:
            raise BridgeFailed("unexpected")
        return res.status, body
    finally:
        conn.close()


def _pinned(conn: http.client.HTTPSConnection, fingerprint: str) -> None:
    sock = conn.sock
    der = sock.getpeercert(binary_form=True) if isinstance(sock, ssl.SSLSocket) else None
    if der is None or not hmac.compare_digest(hashlib.sha256(der).hexdigest(), fingerprint):
        raise BridgeFailed("pin_mismatch")
