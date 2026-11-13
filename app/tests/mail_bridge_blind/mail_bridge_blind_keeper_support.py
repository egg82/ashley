"""The keeper as its own program: a copy of `deploy/mail-bridge` run with `python -I` from an empty directory, so nothing
of `ashley` can be imported; a fake app speaking the keeper's routes and a fake Bridge that rewrites `vault.enc` as Bridge
does and writes a cache (the build's decisions are listed in `mail_bridge_blind_support`)."""

import base64
import json
import os
import shutil
import socket
import ssl
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from ashley.mail import proton_tls

REPO = Path(__file__).resolve().parents[3]
DEPLOY = REPO / "deploy" / "mail-bridge"
KEEPER = DEPLOY / "keeper.py"
ROUTES = "/api/mail-bridge/keeper"
TOKEN = "keeper-token-Zq81xv"
SEED_VAULT = b"SEEDVAULT-0001"
SEED_GENERATION = 3
HEARTBEAT_S, FENCE_S = 0.2, 1.5
CACHE_MARK = b"CACHEBYTES-e4b1"
BRIDGE_HOME = Path(".config/protonmail/bridge-v3")

FAKE_BRIDGE = '''
import os, pathlib, sys, time
d, cache = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
vault = d / "vault.enc"
(d / "bridge.pid").write_text(str(os.getpid()))
saw = vault.read_bytes() if vault.exists() else b"<none>"
(d / "bridge-saw").write_bytes(saw)


def replace(data):
    tmp = d / "vault.tmp"
    tmp.write_bytes(data)
    os.replace(tmp, vault)


if "refresh" in sys.argv[3:]:
    replace(saw + b"+refresh")
cache.mkdir(parents=True, exist_ok=True)
(cache / "messages.db").write_bytes(%r * 20000)
(d / "up").write_text("1")
while True:
    t = d / "rewrite"
    if t.exists():
        data = t.read_bytes()
        t.unlink()
        replace(data)
    if (d / "exit").exists():
        sys.exit(3)
    time.sleep(0.02)
''' % CACHE_MARK

DRIVER = '''
import pathlib, subprocess, sys
here = pathlib.Path(__file__).parent
sys.path.insert(0, str(here))
import keeper, keeper_process
from keeper_files import CONFIG
from keeper_link import BridgeError

keeper.POLL_S = 0.02


class Link:
    def watch(self, on_event): pass
    def close(self): pass
    def export_certificate(self, directory): raise BridgeError("no gRPC in the suite")


class Process:
    def __init__(self, popen):
        self.popen, self.link = popen, Link()

    def alive(self):
        return self.popen.poll() is None

    def kill(self):
        self.popen.kill()
        self.popen.wait(10)


def start(home, binary=None):
    argv = [sys.executable, str(here / "fake_bridge.py"), str(home / CONFIG), str(home / "cache")]
    return Process(subprocess.Popen(argv + (["refresh"] if sys.argv[1:] == ["refresh"] else [])))


keeper_process.start = start
raise SystemExit(keeper.main())
'''


@dataclass
class Req:
    at: float
    method: str
    path: str
    auth: str
    body: dict[str, Any]


def seed_keychain(tmp: Path) -> bytes:
    """A keychain a first pod would have made, packed as the keeper packs it."""
    sys.path.insert(0, str(DEPLOY))
    from keeper_files import KEYCHAIN, pack_keychain
    home = tmp / "seed-keychain"
    for top in KEYCHAIN:
        target = home / top
        if top.suffix == ".json":
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("{}")
        else:
            target.mkdir(parents=True, exist_ok=True)
            (target / "entry.gpg").write_bytes(b"sealed-key")
    return pack_keychain(home)


@dataclass
class FakeApp:
    """The app's keeper routes with a vault held at a generation. Programmable: `heartbeat_status` (204 is the success),
    `writeback_status` (None answers by the generation rule), `hang_up` (cut every connection without an answer)."""

    token: str = TOKEN
    epoch: int = 7
    vault: bytes = SEED_VAULT
    keychain: bytes = b""
    generation: int = SEED_GENERATION
    heartbeat_status: int = 204
    writeback_status: int | None = None
    hang_up: bool = False
    hang_up_writes: bool = False
    requests: list[Req] = field(default_factory=list[Req])
    server: ThreadingHTTPServer | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def url(self) -> str:
        assert self.server is not None
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def start(self) -> "FakeApp":
        app = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: Any) -> None:
                return

            def _go(self) -> None:
                size = int(self.headers.get("content-length") or 0)
                raw = self.rfile.read(size) if size else b""
                parts = urlsplit(self.path)
                body: dict[str, Any] = json.loads(raw) if raw else {}
                for key, values in parse_qs(parts.query).items():
                    body.setdefault(key, values[0])
                with app.lock:
                    app.requests.append(Req(time.monotonic(), self.command, parts.path.removeprefix(ROUTES),
                                            self.headers.get("authorization", ""), body))
                    if app.hang_up or (app.hang_up_writes and self.command == "PUT"):
                        self.connection.close()
                        return
                    status, out = app.answer(self.command, parts.path.removeprefix(ROUTES), body,
                                             self.headers.get("authorization", ""))
                data = b"" if status == 204 else json.dumps(out).encode()
                self.send_response(status)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_POST = do_PUT = _go

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, args=(0.02,), daemon=True).start()
        return self

    def answer(self, method: str, path: str, body: dict[str, Any], auth: str) -> tuple[int, dict[str, Any]]:
        if auth != f"Bearer {self.token}":
            return 401, {}
        if int(body.get("epoch", -1)) != self.epoch:
            return 409, {}
        if path == "/heartbeat":
            return self.heartbeat_status, {}
        if path == "/vault" and method == "GET":
            return 200, {"generation": self.generation, "vault": base64.b64encode(self.vault).decode(),
                         "keychain": base64.b64encode(self.keychain).decode()}
        if path == "/vault" and method == "PUT":
            if self.writeback_status is not None:
                return self.writeback_status, {}
            if int(body["generation"]) != self.generation:
                return 409, {}
            self.vault = base64.b64decode(body["vault"])
            self.generation += 1
            return 200, {"generation": self.generation}
        return 200, {"applied": True}

    def stop(self) -> None:
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()

    def kinds(self) -> list[str]:
        """The requests so far as `METHOD path`."""
        with self.lock:
            return [f"{r.method} {r.path}" for r in self.requests]

    def puts(self) -> list[Req]:
        with self.lock:
            return [r for r in self.requests if r.method == "PUT"]

    def beats(self) -> list[Req]:
        with self.lock:
            return [r for r in self.requests if r.path == "/heartbeat"]

    def wire_text(self) -> str:
        with self.lock:
            return "\n".join(json.dumps(r.body) for r in self.requests)


def free_ports(n: int) -> list[int]:
    """`n` distinct ports free now: every probe stays bound until all are drawn, so no two draws repeat."""
    probes = [socket.socket() for _ in range(n)]
    try:
        for probe in probes:
            probe.bind(("127.0.0.1", 0))
        return [int(probe.getsockname()[1]) for probe in probes]
    finally:
        for probe in probes:
            probe.close()


class Keeper:
    """The keeper program, `keeper.main()` in a process of its own that no `ashley` is importable from, against `app`,
    its Bridge a stand-in process the driver starts in place of `keeper_process.start` (the image's own test runs the
    real one)."""

    def __init__(self, tmp: Path, app: FakeApp, refresh: bool = True, **env: str) -> None:
        if not app.keychain:
            app.keychain = seed_keychain(tmp)
        self.home = tmp / "home"
        self.dir = self.home / BRIDGE_HOME
        self.cache = self.home / "cache"
        self.dir.mkdir(parents=True)
        program = tmp / "program"
        program.mkdir()
        for source in DEPLOY.glob("keeper*.py"):
            shutil.copy(source, program / source.name)
        (program / "fake_bridge.py").write_text(FAKE_BRIDGE)
        (program / "driver.py").write_text(DRIVER)
        pair = proton_tls.make()
        (tmp / "tls").mkdir()
        (tmp / "tls" / "tls.crt").write_text(pair[proton_tls.CERT_KEY])
        (tmp / "tls" / "tls.key").write_text(pair[proton_tls.KEY_KEY])
        self.out = tmp / "keeper.out"
        control, imap, smtp = free_ports(3)
        settings = {"ASHLEY_URL": app.url, "BRIDGE_TOKEN": app.token, "BRIDGE_EPOCH": str(app.epoch),
                    "BRIDGE_HEARTBEAT_S": str(HEARTBEAT_S), "BRIDGE_FENCE_S": str(FENCE_S),
                    "BRIDGE_CONTROL_PORT": str(control), "BRIDGE_IMAP_PORT": str(imap),
                    "BRIDGE_SMTP_PORT": str(smtp), "BRIDGE_TLS_DIR": str(tmp / "tls"), **env}
        base = {"PATH": os.environ.get("PATH", ""), "HOME": str(self.home), "LANG": "C.UTF-8"}
        with self.out.open("wb") as sink:
            self.proc = subprocess.Popen([sys.executable, "-I", str(program / "driver.py"), *(["refresh"] if refresh else [])],
                                         cwd=program, env={**base, **settings}, stdout=sink, stderr=subprocess.STDOUT)

    def bridge_pid(self) -> int | None:
        path = self.dir / "bridge.pid"
        return int(path.read_text()) if path.exists() and path.read_text() else None

    def bridge_up(self, limit: float = 10.0) -> bool:
        return wait_for(lambda: (self.dir / "up").exists(), limit)

    def bridge_alive(self) -> bool:
        pid = self.bridge_pid()
        if pid is None:
            return False
        try:
            stat = Path(f"/proc/{pid}/stat").read_text()
        except OSError:
            return False
        return stat.rsplit(")", 1)[1].split()[0] != "Z"

    def rewrite_vault(self, data: bytes) -> None:
        """Bridge replaces its vault, as it does on a refresh, a settings change or the end of a sync."""
        tmp = self.dir / "rewrite.tmp"
        tmp.write_bytes(data)
        os.replace(tmp, self.dir / "rewrite")

    def exited(self, limit: float) -> int | None:
        wait_for(lambda: self.proc.poll() is not None, limit)
        return self.proc.poll()

    def output(self) -> str:
        return self.out.read_text(errors="replace")

    def close(self) -> None:
        if self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait(5)
        pid = self.bridge_pid()
        if pid is not None and self.bridge_alive():
            os.kill(pid, 9)


def wait_for(until: Any, limit: float) -> bool:
    deadline = time.monotonic() + limit
    while time.monotonic() < deadline:
        if until():
            return True
        time.sleep(0.02)
    return bool(until())


class FakeKeeperHttp:
    """The keeper's control port as the app's login relay sees it: TLS under a certificate of its own (`cert`), a bearer
    token (`TOKEN`), each step's path and body recorded, the answer from `script`."""

    def __init__(self, script: dict[str, tuple[int, dict[str, Any]]], tmp: Path) -> None:
        self.script = script
        self.steps: list[tuple[str, dict[str, Any]]] = []
        pair = proton_tls.make()
        self.cert = pair[proton_tls.CERT_KEY]
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: Any) -> None:
                return

            def do_POST(self) -> None:
                size = int(self.headers.get("content-length") or 0)
                body: dict[str, Any] = json.loads(self.rfile.read(size)) if size else {}
                if self.headers.get("authorization") != f"Bearer {TOKEN}":
                    status, out = 401, {}
                else:
                    outer.steps.append((self.path, body))
                    status, out = outer.script.get(self.path, (404, {}))
                data = json.dumps(out).encode()
                self.send_response(status)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        (tmp / "keeper.crt").write_text(pair[proton_tls.CERT_KEY])
        (tmp / "keeper.key").write_text(pair[proton_tls.KEY_KEY])
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(tmp / "keeper.crt", tmp / "keeper.key")
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.socket = context.wrap_socket(self.server.socket, server_side=True)
        threading.Thread(target=self.server.serve_forever, args=(0.02,), daemon=True).start()

    @property
    def url(self) -> str:
        return f"https://127.0.0.1:{self.server.server_address[1]}"

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
