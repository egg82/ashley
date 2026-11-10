"""What the fake Bridge holds and how it talks: its state (`Bridge`), a message as it hands one over (`mail`) and the socket
wrapper both protocols read through. Part of `mail_proton_support`, which says what is unverified."""

import socket
import ssl
from dataclasses import dataclass, field
from email import policy
from email.message import EmailMessage
from email.utils import make_msgid

USER = "pat@proton.test"
PASSWORD = "bridge-issued-password"
RECEIVED = "07-Nov-2026 10:00:00 +0000"


@dataclass
class Stored:
    uid: int
    raw: bytes
    flags: set[str]
    received: str


def mail(subject: str, sender: str = "Sam <sam@school.test>", to: str = USER, body: str = "hello there",
         message_id: str | None = "", date: str = "Sat, 07 Nov 2026 10:00:00 +0000", **headers: str) -> bytes:
    """A message as Bridge would hand it over. `message_id` None leaves the header out, '' makes one."""
    built = EmailMessage(policy=policy.SMTP)
    built["From"], built["To"], built["Subject"], built["Date"] = sender, to, subject, date
    if message_id is not None:
        built["Message-ID"] = message_id or make_msgid(domain="school.test")
    for name, value in headers.items():
        built[name.replace("_", "-")] = value
    built.set_content(body)
    return built.as_bytes()


@dataclass
class Bridge:
    """What the fake holds and saw. `folders` maps a folder's name to its messages; `commands` is each IMAP command word
    with its folder or uids, never a password; `sent` is (envelope sender, recipients, message)."""

    user: str = USER
    password: str = PASSWORD
    folders: dict[str, list[Stored]] = field(default_factory=dict[str, list[Stored]])
    commands: list[str] = field(default_factory=list[str])
    sent: list[tuple[str, list[str], bytes]] = field(default_factory=list[tuple[str, list[str], bytes]])
    refuse: set[str] = field(default_factory=set[str])
    uid_last: bool = False
    logins: int = 0
    _next: int = 1

    def add(self, folder: str, raw: bytes, flags: tuple[str, ...] = (), received: str = RECEIVED) -> int:
        uid = self._next
        self._next += 1
        self.folders.setdefault(folder, []).append(Stored(uid, raw, set(flags), received))
        return uid


class Wire:
    def __init__(self, sock: socket.socket) -> None:
        self.sock: socket.socket = sock
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.buf = b""

    def line(self) -> bytes | None:
        while b"\r\n" not in self.buf:
            data = self.sock.recv(65536)
            if not data:
                return None
            self.buf += data
        out, _, self.buf = self.buf.partition(b"\r\n")
        return out

    def take(self, n: int) -> bytes:
        while len(self.buf) < n:
            self.buf += self.sock.recv(65536)
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def send(self, data: bytes) -> None:
        self.sock.sendall(data)

    def secure(self, context: ssl.SSLContext) -> None:
        self.sock = context.wrap_socket(self.sock, server_side=True)
