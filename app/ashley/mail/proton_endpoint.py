"""Where the app reaches Bridge's IMAP and SMTP, and how it trusts what answers. Bridge's relay in the keeper listens on the
pod's own ports (`proton_pod`) and passes bytes to Bridge's loopback, so a connection is plain until STARTTLS, then under
the certificate Bridge made for itself. That certificate is pinned: its SHA-256, which the keeper reports with each heartbeat
(`ProtonBridge.holder`), must be the one the server shows, whatever name the Service is reached under. A connection whose
certificate is not the pod's is a stale or foreign one, and is refused."""

import hashlib
import hmac
import socket
import ssl
from dataclasses import dataclass, field

from .model import MailFailed


@dataclass(frozen=True)
class Login:
    """Everything a session needs: the Service `hosts` of each site (this site's first), the ports, the `fingerprint` to
    pin, the mailbox `address` and the Bridge `password` issued for its account (left out of `repr`)."""

    hosts: tuple[str, ...]
    imap_port: int
    smtp_port: int
    fingerprint: str
    address: str
    password: str = field(repr=False)


def context() -> ssl.SSLContext:
    """A client context that takes any certificate, for `pinned` to check by fingerprint after the handshake."""
    made = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    made.minimum_version = ssl.TLSVersion.TLSv1_2
    made.check_hostname = False
    made.verify_mode = ssl.CERT_NONE
    return made


def pinned(sock: socket.socket | ssl.SSLSocket, fingerprint: str) -> None:
    """Raises MailFailed `unreachable` unless `sock` is TLS and shows the certificate whose SHA-256 (hex) is
    `fingerprint`."""
    der = sock.getpeercert(binary_form=True) if isinstance(sock, ssl.SSLSocket) else None
    if der is None or not hmac.compare_digest(hashlib.sha256(der).hexdigest(), fingerprint.lower()):
        raise MailFailed("unreachable")
