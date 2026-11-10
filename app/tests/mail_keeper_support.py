"""Fakes at the keeper's boundaries: the app as an HTTP transport that records every call in order, Bridge as a
`BridgeLink` whose logins and users are scripted, and a process whose `vault.enc` a test replaces as a refreshing Bridge
would. The keeper's files are real, in a temporary home."""

import base64
import json
import ssl
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from keeper import Config, Keeper
from keeper_app import AppClient
from keeper_files import CONFIG, VAULT
from keeper_link import LoginEvent, UserEvent, UserInfo

TOKEN = "keeper-token"
CERT_DER = b"not-really-a-certificate"


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


@dataclass
class FakeApp:
    """The app's keeper routes. `answer` forces a status for the next calls to a path, or `None` makes them time out."""

    generation: int = 0
    vault: bytes | None = None
    keychain: bytes | None = None
    calls: list[str] = field(default_factory=lambda: list[str]())
    written: list[tuple[int, bytes]] = field(default_factory=lambda: list[tuple[int, bytes]]())
    events: list[dict[str, object]] = field(default_factory=lambda: list[dict[str, object]]())
    beats: list[str | None] = field(default_factory=lambda: list[str | None]())
    forced: dict[str, int | None] = field(default_factory=lambda: dict[str, int | None]())

    def transport(self, method: str, url: str, headers: Mapping[str, str], body: bytes | None,
                  timeout: float) -> tuple[int, bytes]:
        assert headers["Authorization"] == f"Bearer {TOKEN}"
        path = urlsplit(url).path.rsplit("/", 1)[-1]
        self.calls.append(path)
        if path in self.forced:
            status = self.forced[path]
            if status is None:
                raise TimeoutError("no answer")
            return status, b"{}"
        data: dict[str, Any] = json.loads(body) if body else {}
        if path == "vault" and method == "GET":
            enc = base64.b64encode
            return 200, json.dumps({"generation": self.generation,
                                    "vault": None if self.vault is None else enc(self.vault).decode(),
                                    "keychain": None if self.keychain is None else enc(self.keychain).decode()}).encode()
        if path == "vault":
            if data["generation"] != self.generation:
                return 409, b"{}"
            self.generation += 1
            self.vault, self.keychain = base64.b64decode(data["vault"]), base64.b64decode(data["keychain"])
            self.written.append((data["generation"], self.vault))
            return 200, json.dumps({"generation": self.generation}).encode()
        if path == "heartbeat":
            self.beats.append(data["certificate_sha256"])
        if path == "events":
            self.events.append(data)
            return 200, b'{"applied": true}'
        return 204, b""


@dataclass
class FakeBridge:
    """Bridge's link: `logins` are the answers to login calls in turn; `on_login` runs when one is asked."""

    users_held: dict[str, UserInfo] = field(default_factory=lambda: dict[str, UserInfo]())
    logins: list[LoginEvent] = field(default_factory=lambda: list[LoginEvent]())
    asked: list[str] = field(default_factory=lambda: list[str]())
    on_login: Callable[[], None] = lambda: None
    on_event: Callable[[UserEvent], None] = lambda event: None
    certificate: Path | None = None
    closed: bool = False

    def watch(self, on_event: Callable[[UserEvent], None]) -> None:
        self.on_event = on_event

    def _next(self, call: str) -> LoginEvent:
        self.asked.append(call)
        self.on_login()
        return self.logins.pop(0)

    def login(self, username: str, password: str, verified: bool = False) -> LoginEvent:
        return self._next(f"login {username}" + (" verified" if verified else ""))

    def second_factor(self, username: str, code: str) -> LoginEvent:
        return self._next(f"second_factor {username}")

    def mailbox_password(self, username: str, password: str) -> LoginEvent:
        return self._next(f"mailbox_password {username}")

    def abort(self, username: str) -> None:
        self.asked.append(f"abort {username}")

    def users(self) -> list[UserInfo]:
        return list(self.users_held.values())

    def user(self, user_id: str) -> UserInfo:
        return self.users_held[user_id]

    def set_split(self, user_id: str, active: bool) -> None:
        self.asked.append(f"split {user_id}")
        held = self.users_held[user_id]
        self.users_held[user_id] = UserInfo(held.id, held.state, active, held.addresses, held.password)

    def remove(self, user_id: str) -> None:
        self.asked.append(f"remove {user_id}")
        del self.users_held[user_id]

    def export_certificate(self, directory: str) -> None:
        (Path(directory) / "cert.pem").write_text(ssl.DER_cert_to_PEM_cert(CERT_DER))

    def close(self) -> None:
        self.closed = True


@dataclass
class FakeProcess:
    link: FakeBridge
    killed: bool = False
    exited: bool = False

    def alive(self) -> bool:
        return not self.killed and not self.exited

    def kill(self) -> None:
        self.killed = True


@dataclass
class Rig:
    keeper: Keeper
    app: FakeApp
    bridge: FakeBridge
    process: FakeProcess
    home: Path
    clock: Clock
    commands: list[Sequence[str]]

    def bridge_writes_vault(self, content: bytes) -> None:
        """Bridge replaces `vault.enc`, as it does when it refreshes its tokens."""
        path = self.home / VAULT
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)


def rig(home: Path, app: FakeApp | None = None, heartbeat_s: float = 5.0, fence_s: float = 30.0) -> Rig:
    app = app or FakeApp()
    clock = Clock()
    bridge = FakeBridge()
    process = FakeProcess(bridge)
    commands: list[Sequence[str]] = []
    client = AppClient("http://app.test", 3, TOKEN, 5.0, app.transport)
    keeper = Keeper(Config(3, heartbeat_s, fence_s, home), client, commands.append, lambda: process, clock, clock.sleep)
    return Rig(keeper, app, bridge, process, home, clock, commands)


def make_keychain(home: Path) -> bytes:
    """A keychain a first pod would have made: a `pass` store, a GPG home and Bridge's marker files."""
    from keeper_files import KEYCHAIN, pack_keychain
    for top in KEYCHAIN:
        target = home / top
        if top.suffix == ".json":
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("{}")
        else:
            target.mkdir(parents=True, exist_ok=True)
            (target / "entry.gpg").write_bytes(b"sealed-key")
    return pack_keychain(home)


__all__ = ["CONFIG"]
