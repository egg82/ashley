"""The fake Proton Mail Bridge: one IMAP and one SMTP server on localhost sockets over the same accounts, with no import from
`ashley`. SMTP (RFC 5321) takes EHLO, AUTH PLAIN and LOGIN, MAIL FROM, RCPT TO, DATA, RSET, NOOP, QUIT and, in 'starttls'
mode, STARTTLS; a delivered message is kept with its envelope (`Delivered`) and, like Bridge's, saved in the sender's Sent
by the server itself (`save_to_sent`), so a client that also saves one duplicates it. A test makes it fail the way a
server does (`refuse_rcpt`, `data_code`, `drop_after_data`) and counts DATA attempts, which a send must make once.
Error replies echo the address and a secret-looking word, so a log that copies a server's reply shows it.
Unverified, hand-written: Bridge's real replies and its saving to Sent."""

import base64
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from mail_proton_blind_imap_support import LEAK, Behaviour, serve_imap
from mail_proton_blind_store_support import Account
from mail_proton_blind_wire_support import Cert, Listener, Wire


@dataclass
class Delivered:
    user: str
    mail_from: str
    rcpts: list[str]
    data: bytes


@dataclass
class SmtpBehaviour:
    refuse_rcpt: set[str] = field(default_factory=lambda: set[str]())
    data_code: int = 250
    drop_after_data: bool = False
    save_to_sent: bool = True
    greeting: str | None = None


def clean(arg: str) -> str:
    start, end = arg.find("<"), arg.find(">")
    return arg[start + 1:end] if start >= 0 and end > start else arg.strip()


class SmtpSession:
    def __init__(self, wire: Wire, accounts: dict[str, Account], cert: Cert, tls: str, behaviour: SmtpBehaviour,
                 out: "SmtpLog") -> None:
        self.w, self.accounts, self.cert, self.tls, self.b, self.out = wire, accounts, cert, tls, behaviour, out
        self.secure = tls != "starttls"
        self.user: str | None = None
        self.sender, self.rcpts = "", list[str]()

    def say(self, text: str) -> None:
        self.w.write(text.encode() + b"\r\n")

    def run(self) -> None:
        self.say(self.b.greeting or "220 bridge.test ESMTP ready")
        if self.b.greeting is not None:
            return
        while (raw := self.w.line()) is not None:
            line = raw.decode("utf-8", errors="replace")
            verb, _, rest = line.partition(" ")
            if self.command(verb.upper(), rest):
                return

    def command(self, verb: str, rest: str) -> bool:
        if verb in ("EHLO", "HELO"):
            extra = "250-STARTTLS\r\n" if self.tls == "starttls" and not self.secure else ""
            self.say(f"250-bridge.test\r\n{extra}250-SIZE 36700160\r\n250 AUTH PLAIN LOGIN")
        elif verb == "STARTTLS" and self.tls == "starttls" and not self.secure:
            self.say("220 go ahead")
            self.w.upgrade(self.cert.context)
            self.secure = True
        elif verb == "AUTH":
            self.auth(rest)
        elif verb == "MAIL":
            self.mail(rest)
        elif verb == "RCPT":
            self.rcpt(rest)
        elif verb == "DATA":
            return self.data()
        elif verb == "RSET":
            self.sender, self.rcpts = "", []
            self.say("250 ok")
        elif verb == "NOOP":
            self.say("250 ok")
        elif verb == "QUIT":
            self.say("221 bye")
            return True
        else:
            self.say("502 not implemented")
        return False

    def auth(self, rest: str) -> None:
        mechanism, _, initial = rest.partition(" ")
        if not self.secure:
            self.say("530 STARTTLS first")
            return
        if mechanism.upper() == "PLAIN":
            if not initial:
                self.say("334 ")
                initial = (self.w.line() or b"").decode()
            _, user, password = base64.b64decode(initial).decode().split("\x00")
        elif mechanism.upper() == "LOGIN":
            self.say("334 VXNlcm5hbWU6")
            user = base64.b64decode(self.w.line() or b"").decode()
            self.say("334 UGFzc3dvcmQ6")
            password = base64.b64decode(self.w.line() or b"").decode()
        else:
            self.say("504 mechanism")
            return
        account = self.accounts.get(user.lower())
        if account is None or account.password != password:
            self.say(f"535 5.7.8 credentials for {user} refused, {LEAK}")
            return
        self.user = account.address
        self.say("235 2.7.0 authenticated")

    def mail(self, rest: str) -> None:
        if self.user is None:
            self.say("530 5.7.0 authentication required")
            return
        self.sender, self.rcpts = clean(rest.partition(":")[2].split(" ")[0]), []
        self.out.senders.append(self.sender)
        self.say("250 ok")

    def rcpt(self, rest: str) -> None:
        address = clean(rest.partition(":")[2])
        if address.lower() in {r.lower() for r in self.b.refuse_rcpt}:
            self.say(f"550 5.1.1 no such user {address}, {LEAK}")
            return
        self.rcpts.append(address)
        self.say("250 ok")

    def data(self) -> bool:
        if self.user is None or not self.rcpts:
            self.say("503 need MAIL and RCPT first")
            return False
        self.say("354 end with <CRLF>.<CRLF>")
        lines: list[bytes] = []
        while (raw := self.w.line()) is not None and raw != b".":
            lines.append(raw[1:] if raw.startswith(b"..") else raw)
        self.out.attempts += 1
        if self.b.drop_after_data:
            return True
        if self.b.data_code != 250:
            self.say(f"{self.b.data_code} 4.3.0 not accepted for {self.rcpts[0]}, {LEAK}")
            return False
        done = Delivered(self.user, self.sender, list(self.rcpts), b"\r\n".join(lines) + b"\r\n")
        self.out.delivered.append(done)
        if self.b.save_to_sent:
            self.out.on_delivered(done)
        self.say("250 2.0.0 queued")
        return False


class SmtpLog:
    def __init__(self, on_delivered: Callable[[Delivered], None]) -> None:
        self.delivered: list[Delivered] = []
        self.attempts = 0
        self.senders: list[str] = []
        self.on_delivered = on_delivered


class FakeBridge:
    """`accounts` by address; `imap` and `smtp` are the listeners (`.port`); `tls` is 'none', 'implicit' or 'starttls'."""

    def __init__(self, tls: str = "none") -> None:
        self.accounts: dict[str, Account] = {}
        self.cert = Cert()
        self.tls = tls
        self.imap_behaviour, self.smtp_behaviour = Behaviour(), SmtpBehaviour()
        self.smtp = SmtpLog(self.save_sent)
        self.imap_listener = Listener(serve_imap(self.accounts, self.cert, tls, self.imap_behaviour), self.cert, tls)

        def serve(wire: Wire) -> None:
            SmtpSession(wire, self.accounts, self.cert, tls, self.smtp_behaviour, self.smtp).run()

        self.smtp_listener = Listener(serve, self.cert, tls)

    @property
    def imap_port(self) -> int:
        return self.imap_listener.port

    @property
    def smtp_port(self) -> int:
        return self.smtp_listener.port

    def account(self, address: str, password: str = "bridge-password") -> Account:
        made = Account(address, password)
        self.accounts[address.lower()] = made
        return made

    def save_sent(self, done: Delivered) -> None:
        self.accounts[done.user.lower()].add("Sent", done.data, ("\\Seen",), datetime.now(UTC))

    def stop(self) -> None:
        self.imap_listener.stop()
        self.smtp_listener.stop()
