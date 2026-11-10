"""A fake Proton Mail Bridge on localhost sockets: IMAP and SMTP, both STARTTLS under a self-signed certificate (the
one `fingerprint` is of), serving the commands `ashley.mail.imap` sends and no others. Hand-written from RFC 3501 and
RFC 5321 and from what `imaplib` and `smtplib` send, never captured from Bridge, so a test over it shows the adapter does
what it means to, not that Bridge answers so. Unverified against Bridge: that a copy into `Labels/<name>` labels a message
and a delete from it unlabels one, that `Archive`, `Spam` and `Trash` are its folder names, and that it answers
`FETCH` with `UID` first. `uid_last` answers with it last, as the RFC allows."""

import base64
import hashlib
import socketserver
import ssl
import tempfile
import threading
from dataclasses import replace
from pathlib import Path

from ashley import services
from ashley.connections.connections import Connections
from ashley.mail import config as mail_config, proton_tls
from ashley.mail.imap import ImapMailbox
from ashley.mail.mailbox import Mailbox
from ashley.mail.proton_bridge import Account as BridgeAccount, AccountState, Holder, NullProtonBridge, ProtonBridge
from mail_proton_imap import ImapSide
from mail_proton_state import PASSWORD, USER, Bridge, Wire, mail
from money_support import HeldConnections

__all__ = ["ALANA", "HOME", "PASSWORD", "USER", "Bridge", "FakeBridge", "mail", "stocked", "wire"]


class SmtpSide:
    def __init__(self, bridge: Bridge, context: ssl.SSLContext, wire: Wire) -> None:
        self.bridge, self.context, self.wire = bridge, context, wire

    def run(self) -> None:
        self.wire.send(b"220 fake bridge\r\n")
        sender, authed, tls = "", False, False
        rcpts: list[str] = []
        while (line := self.wire.line()) is not None:
            text = line.decode()
            word = text.split(" ", 1)[0].upper()
            if word == "EHLO":
                self.wire.send(b"250-fake\r\n" + (b"250-STARTTLS\r\n" if not tls else b"250-AUTH PLAIN\r\n") + b"250 8BITMIME\r\n")
            elif word == "STARTTLS":
                self.wire.send(b"220 go\r\n")
                self.wire.secure(self.context)
                tls = True
            elif word == "AUTH":
                got = base64.b64decode(text.split(" ")[2]).split(b"\x00")
                authed = got[1:] == [self.bridge.user.encode(), self.bridge.password.encode()]
                self.wire.send(b"235 ok\r\n" if authed else b"535 5.7.8 refused\r\n")
            elif word == "MAIL":
                sender, rcpts = text.split("<", 1)[1].split(">")[0], []
                self.wire.send(b"250 ok\r\n")
            elif word == "RCPT":
                to = text.split("<", 1)[1].split(">")[0]
                refused = to in self.bridge.refuse
                rcpts += [] if refused else [to]
                self.wire.send(b"550 no such user\r\n" if refused else b"250 ok\r\n")
            elif word == "DATA":
                self.data(sender, rcpts)
            elif word == "QUIT":
                self.wire.send(b"221 bye\r\n")
                return
            else:
                self.wire.send(b"250 ok\r\n")

    def data(self, sender: str, rcpts: list[str]) -> None:
        self.wire.send(b"354 go\r\n")
        lines: list[bytes] = []
        while (got := self.wire.line()) is not None and got != b".":
            lines.append(got[1:] if got.startswith(b"..") else got)
        self.bridge.sent.append((sender, rcpts, b"\r\n".join(lines) + b"\r\n"))
        self.wire.send(b"250 queued\r\n")


class FakeBridge:
    """Both servers, started on free ports of 127.0.0.1; `bridge` is their one state."""

    def __init__(self) -> None:
        pair = proton_tls.make()
        self._dir = tempfile.TemporaryDirectory()
        crt, key = Path(self._dir.name, "c.pem"), Path(self._dir.name, "k.pem")
        crt.write_text(pair[proton_tls.CERT_KEY])
        key.write_text(pair[proton_tls.KEY_KEY])
        self.context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.context.load_cert_chain(crt, key)
        self.fingerprint = hashlib.sha256(ssl.PEM_cert_to_DER_cert(pair[proton_tls.CERT_KEY])).hexdigest()
        self.bridge = Bridge()
        self._servers = [self._serve(ImapSide), self._serve(SmtpSide)]
        self.imap_port: int = self._servers[0].server_address[1]
        self.smtp_port: int = self._servers[1].server_address[1]

    def _serve(self, protocol: type[ImapSide] | type[SmtpSide]) -> socketserver.ThreadingTCPServer:
        outer = self

        class Handler(socketserver.BaseRequestHandler):
            def handle(self) -> None:
                try:
                    protocol(outer.bridge, outer.context, Wire(self.request)).run()
                except (OSError, ssl.SSLError, ValueError, IndexError):
                    pass

        class Server(socketserver.ThreadingTCPServer):
            daemon_threads = True
            allow_reuse_address = True

        server = Server(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
        return server

    def reset(self) -> Bridge:
        self.bridge = Bridge()
        return self.bridge

    def stop(self) -> None:
        for server in self._servers:
            server.shutdown()
            server.server_close()
        self._dir.cleanup()


HOME, ALANA = 1, 7
FOLDERS = ("INBOX", "Archive", "Sent", "Drafts", "Trash", "Spam", "Labels/School", "Labels/Café")


class Record(NullProtonBridge):
    """The record of Bridge's keeping as the adapter reads it: the accounts and the holder's certificate."""

    def __init__(self, accounts: tuple[BridgeAccount, ...], certificate: str | None) -> None:
        self._accounts, self._certificate = accounts, certificate

    async def accounts(self) -> tuple[BridgeAccount, ...]:
        return self._accounts

    async def holder(self) -> Holder:
        return Holder(3, "birch", "pod", 1.0, self._certificate)


def stocked(fake: FakeBridge) -> Bridge:
    """A fresh state with every folder, empty."""
    bridge = fake.reset()
    for name in FOLDERS:
        bridge.folders[name] = []
    return bridge


def wire(fake: FakeBridge, state: AccountState = "connected", synced: bool = True, certificate: str | None = "",
         addresses: tuple[str, ...] = (USER,), **changed: int) -> mail_config.MailConfig:
    """Register the adapter over `fake`, one Proton connection of ALANA (id 1) and the record that says what Bridge holds;
    returns the config in use, the shipped one with `changed` settings."""
    config = replace(mail_config.load(), **changed)
    held = HeldConnections()
    held.connect(HOME, "bridge://proton", PASSWORD, "proton", ALANA)
    services.register(Connections, held)
    account = BridgeAccount(1, 1, "user-1", state, addresses, 3 if synced else 2, 3, None)
    pinned = fake.fingerprint if certificate == "" else certificate
    services.register(ProtonBridge, Record((account,), pinned))
    services.register(Mailbox, ImapMailbox(("127.0.0.1",), config, fake.imap_port, fake.smtp_port))
    return config
