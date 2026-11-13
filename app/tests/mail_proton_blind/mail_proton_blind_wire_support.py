"""Sockets for the fake Bridge, with no import from `ashley`: a buffered line and byte reader over a socket that can be
upgraded to TLS, a threaded TCP server that accepts plain or implicit-TLS connections, and the self-signed certificate a
fake Bridge serves under (Bridge's own is self-signed too; the design pins it by fingerprint)."""

import hashlib
import socket
import socketserver
import ssl
import tempfile
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from ipaddress import ip_address
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID


class Wire:
    def __init__(self, sock: socket.socket | ssl.SSLSocket) -> None:
        self.sock: socket.socket | ssl.SSLSocket = sock
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.buf = b""

    def fill(self) -> bool:
        try:
            chunk = self.sock.recv(65536)
        except (OSError, ssl.SSLError):
            return False
        self.buf += chunk
        return bool(chunk)

    def line(self) -> bytes | None:
        while b"\n" not in self.buf:
            if not self.fill():
                return None
        raw, _, self.buf = self.buf.partition(b"\n")
        return raw.rstrip(b"\r")

    def read(self, n: int) -> bytes | None:
        while len(self.buf) < n:
            if not self.fill():
                return None
        data, self.buf = self.buf[:n], self.buf[n:]
        return data

    def write(self, data: bytes) -> bool:
        try:
            self.sock.sendall(data)
        except OSError:
            return False
        return True

    def upgrade(self, context: ssl.SSLContext) -> None:
        self.sock = context.wrap_socket(self.sock, server_side=True)
        self.buf = b""

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


class Cert:
    """A self-signed certificate and key on disk, the context that serves it, and its SHA-256 fingerprint (hex of the DER)."""

    def __init__(self) -> None:
        key = ec.generate_private_key(ec.SECP256R1())
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "bridge.test")])
        now = datetime.now(UTC)
        cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
                .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=5))
                .not_valid_after(now + timedelta(days=2))
                .add_extension(x509.SubjectAlternativeName([x509.DNSName("bridge.test"), x509.DNSName("localhost"),
                                                            x509.IPAddress(ip_address("127.0.0.1"))]),
                               critical=False)
                .sign(key, hashes.SHA256()))
        self.pem = cert.public_bytes(serialization.Encoding.PEM).decode()
        self.fingerprint = hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).hexdigest()
        folder = Path(tempfile.mkdtemp(prefix="fake-bridge-cert-"))
        (folder / "c.pem").write_text(self.pem)
        (folder / "k.pem").write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                         serialization.NoEncryption()))
        self.context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.context.load_cert_chain(folder / "c.pem", folder / "k.pem")


class Listener:
    """Accepts connections on 127.0.0.1 and runs `serve(wire)` for each on its own thread; `tls` 'implicit' wraps first."""

    def __init__(self, serve: Callable[[Wire], None], cert: Cert, tls: str) -> None:
        listener = self

        class Handler(socketserver.BaseRequestHandler):
            def handle(self) -> None:
                listener.accepted += 1
                wire = Wire(self.request)
                try:
                    if listener.tls == "implicit":
                        wire.upgrade(listener.cert.context)
                    serve(wire)
                except (OSError, ssl.SSLError):
                    pass
                finally:
                    wire.close()

        class Server(socketserver.ThreadingTCPServer):
            allow_reuse_address = True
            daemon_threads = True

        self.cert, self.tls, self.accepted = cert, tls, 0
        self.server = Server(("127.0.0.1", 0), Handler)
        self.port: int = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, args=(0.01,), daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
