"""Harness for the herdr bridge blind suite: the Api over real Auth, Sessions and Herdr with a fake `herdr` as the
only thing outside the process, plus a real mutual-TLS server for the transport checks."""

import json
import time
import uuid
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path

from herdr_bridge.api import Api, Request, Response
from herdr_bridge.auth import Auth
from herdr_bridge.config import Config
from herdr_bridge.herdr import Herdr
from herdr_bridge.install import init
from herdr_bridge.logs import Log
from herdr_bridge.sessions import Sessions
from herdr_bridge_blind_fake import FakeAgent, FakeHerdr
from herdr_bridge_blind_pki import Pki, write_pair

PERSON = "person-zq9"
PROMPT_MARK = "PROMPTMARK-8f3a"
LABEL_MARK = "labelmark-q7"
BODY = dict[str, object]


class MemoryLog(Log):
    def __init__(self) -> None:
        self.lines: list[str] = []

    def emit(self, line: str) -> None:
        self.lines.append(line)

    def text(self) -> str:
        return "\n".join(self.lines)


class CiHeaders(Mapping[str, str]):
    """Header names are case-insensitive on the wire; the Api may look them up in any case."""

    def __init__(self, items: Mapping[str, str]) -> None:
        self.items_ = {k.lower(): v for k, v in items.items()}

    def __getitem__(self, key: str) -> str:
        return self.items_[key.lower()]

    def __iter__(self) -> Iterator[str]:
        return iter(self.items_)

    def __len__(self) -> int:
        return len(self.items_)


@dataclass
class Bridge:
    api: Api
    herdr: FakeHerdr
    log: MemoryLog
    config: Config
    config_path: Path
    root: Path
    outside: Path
    token: str
    fingerprint: str
    state_dir: Path
    sessions: Sessions

    def call(
        self,
        method: str,
        path: str,
        body: object = None,
        *,
        token: str | None = "",
        person: str | None = PERSON,
        query: Mapping[str, str] | None = None,
        raw: bytes | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Response:
        hdrs: dict[str, str] = {}
        use = self.token if token == "" else token
        if use is not None:
            hdrs["Authorization"] = f"Bearer {use}"
        if person is not None:
            hdrs["X-Ashley-Person"] = person
        hdrs.update(headers or {})
        data = raw if raw is not None else (b"" if body is None else json.dumps(body).encode())
        return self.api.handle(Request(method, path, dict(query or {}), CiHeaders(hdrs), data))

    def get(self, path: str, *, token: str | None = "", person: str | None = PERSON, **q: str) -> Response:
        return self.call("GET", path, token=token, person=person, query=q)

    def post(self, path: str, body: object = None, *, token: str | None = "", person: str | None = PERSON) -> Response:
        return self.call("POST", path, body, token=token, person=person)

    def add(
        self,
        name: str,
        status: str = "idle",
        cwd: str = "/home/person/work",
        agent: str = "claude",
        with_session: bool = True,
        seq: int = 7,
    ) -> FakeAgent:
        made = FakeAgent(str(uuid.uuid4()), name, status, cwd, seq, agent, with_session)
        return self.herdr.add(made)

    def mkdir(self, *parts: str) -> Path:
        d = self.root.joinpath(*parts)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def start(self, directory: object, label: object = "newone", **extra: object) -> Response:
        return self.post("/v1/sessions", {"dir": str(directory), "label": label, **extra})

    def changes(self) -> list[tuple[str, ...]]:
        return self.herdr.changes()


def no_pause(seconds: float) -> None:
    time.sleep(min(seconds, 0.005))


def build_bridge(tmp: Path, pki: Pki, fake: FakeHerdr | None = None, extra_roots: tuple[Path, ...] = ()) -> Bridge:
    root = (tmp / "work").resolve()
    outside = (tmp / "elsewhere").resolve()
    root.mkdir()
    outside.mkdir()
    state = tmp / "state"
    state.mkdir()
    ca = tmp / "ca.pem"
    ca.write_bytes(pki.ca.cert_pem)
    roots = tuple(str(r.resolve()) for r in (root, *extra_roots))
    config = Config("127.0.0.1", 0, roots, str(state), str(ca), start_timeout_ms=500)
    config_path = tmp / "config.json"
    token, fingerprint = init(config, config_path, lambda cert, key: write_pair(pki.server, cert, key))
    herdr_fake = fake or FakeHerdr()
    log = MemoryLog()
    herdr = Herdr(herdr_fake, 5.0)
    sessions = Sessions(herdr, roots, config.start_timeout_ms, log, settle_s=0.05, pause=no_pause)
    api = Api(Auth(state), sessions, herdr, log)
    return Bridge(api, herdr_fake, log, config, config_path, root, outside, token, fingerprint, state, sessions)


SID = "11111111-2222-4333-8444-555555555555"
ROUTES = [
    ("GET", "/v1/whoami", None),
    ("GET", "/v1/sessions", None),
    ("GET", f"/v1/sessions/{SID}/read", None),
    ("POST", f"/v1/sessions/{SID}/prompt", {"text": "hello"}),
    ("POST", "/v1/sessions", {"dir": "/tmp", "label": "abc"}),
    ("POST", f"/v1/sessions/{SID}/close", None),
]


def restarted(b: Bridge) -> Api:
    """A new Api over the same state directory and the same herdr: what a service restart gives."""
    herdr = Herdr(b.herdr, 5.0)
    sessions = Sessions(herdr, b.config.roots, b.config.start_timeout_ms, b.log, settle_s=0.05, pause=no_pause)
    return Api(Auth(b.state_dir), sessions, herdr, b.log)


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-Ashley-Person": PERSON}


def send(api: Api, method: str, path: str, headers: Mapping[str, str], body: object = None) -> Response:
    data = b"" if body is None else json.dumps(body).encode()
    return api.handle(Request(method, path, {}, CiHeaders(headers), data))
