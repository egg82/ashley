"""The keeper: the program in Proton Bridge's pod that keeps Bridge's vault safe in the app's record and ends Bridge when
it cannot (`decisions.md`, "Bridge runs as a leased singleton whose vault outlives its pod"). It imports nothing from the
app. The image runs `import keeper; keeper.main()`.

It fetches the vault and keychain for its epoch, installs them, starts Bridge with its gRPC frontend, and then:

- **writes the vault back before it handles anything else.** Every action the keeper takes (a heartbeat, an event it relays,
  a login step it answers, a connection it relays) starts in `turn()`, which first looks at `vault.enc` and, when Bridge
  replaced it, writes it back with the generation it holds. A login's long wait for Bridge sits outside the turn, and its
  answer is sent through one, so the app is never told an account is connected before its session is stored;
- **ends Bridge, and the pod, when it cannot write back**: a write-back refused or unanswered, a heartbeat refused, or no
  heartbeat answered for `fence_s`;
- relays user events to the app, answers the room's login steps (`serve`) and relays Bridge's loopback IMAP and SMTP to the
  pod's ports (`keeper_relay`).

Logs `proton_bridge.written_back` (epoch, generation, bytes) and `proton_bridge.stopped` (epoch, reason) as key=value lines,
never a token, an address or the vault."""

import contextlib
import hashlib
import os
import signal
import ssl
import subprocess
import threading
import time
from collections.abc import Callable, Generator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import keeper_files
from keeper_app import AppClient, AppUnreachable, Refused
from keeper_link import BridgeError, BridgeLink, LoginEvent, Stopped, UserEvent
from keeper_log import emit

POLL_S = 0.5


@dataclass(frozen=True)
class Config:
    epoch: int
    heartbeat_s: float
    fence_s: float
    home: Path


class Process(Protocol):
    """A running Bridge process and a link to it, as the keeper starts and ends them."""

    @property
    def link(self) -> BridgeLink: ...

    def alive(self) -> bool: ...

    def kill(self) -> None: ...


class Keeper:
    def __init__(self, config: Config, app: AppClient, run: keeper_files.Runner, start: Callable[[], Process],
                 clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep) -> None:
        self._cfg = config
        self._app = app
        self._run = run
        self._start = start
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.RLock()
        self.stopped = threading.Event()
        self.reason = ""
        self._process: Process | None = None
        self._link: BridgeLink | None = None
        self._generation = 0
        self._written: str | None = None
        self._certificate: str | None = None
        self._last_beat = 0.0
        self._last_answered = 0.0
        self._synced: set[str] = set()
        self._pending_login = ""

    def run(self) -> int:
        """Start Bridge and keep it until it must end, which is always a failure of the pod: the exit status, 1."""
        try:
            self.boot()
            while not self.stopped.is_set():
                self.step()
                self._sleep(POLL_S)
        except Stopped:
            pass
        finally:
            self._kill()
        return 1

    def boot(self) -> None:
        """Install the vault and start Bridge. Raises Stopped when the vault cannot be fetched."""
        try:
            fetched = self._app.fetch_vault()
        except (Refused, AppUnreachable) as e:
            self.stop(f"vault_fetch_{type(e).__name__.lower()}")
            raise Stopped from e
        self._last_answered = self._clock()
        self._last_beat = self._last_answered - self._cfg.heartbeat_s
        self._generation = fetched.generation
        keeper_files.install(self._cfg.home, fetched.vault, fetched.keychain, self._run)
        self._written = None if fetched.vault is None else keeper_files.digest(fetched.vault)
        self._process = self._start()
        self._link = self._process.link
        self._link.watch(self.on_event)
        self._certificate = self._certificate_fingerprint()

    def step(self) -> None:
        """One pass: Bridge still running, the vault, then the heartbeat when it is due, then the fence."""
        if self._process is not None and not self._process.alive():
            self.stop("bridge_exited")
        with self.turn():
            now = self._clock()
            if now - self._last_beat >= self._cfg.heartbeat_s:
                self._last_beat = now
                self._beat(now)
            if now - self._last_answered >= self._cfg.fence_s:
                self.stop("fence")

    def _beat(self, now: float) -> None:
        try:
            self._app.heartbeat(self._certificate)
            self._last_answered = now
        except Refused:
            self.stop("heartbeat_refused")
        except AppUnreachable:
            pass

    @contextlib.contextmanager
    def turn(self) -> Generator[None]:
        """Everything the keeper does for anyone happens inside this: the vault is written back first. Raises Stopped."""
        with self._lock:
            self._raise_if_stopped()
            self._write_back_if_changed()
            yield
            self._raise_if_stopped()

    def _write_back_if_changed(self) -> None:
        vault = keeper_files.vault_bytes(self._cfg.home)
        if vault is None or keeper_files.digest(vault) == self._written:
            return
        keychain = keeper_files.pack_keychain(self._cfg.home)
        try:
            self._generation = self._app.write_back(self._generation, vault, keychain)
        except (Refused, AppUnreachable) as e:
            self.stop(f"write_back_{type(e).__name__.lower()}")
            raise Stopped from e
        self._written = keeper_files.digest(vault)
        emit("proton_bridge.written_back", epoch=self._cfg.epoch, generation=self._generation, bytes=len(vault))

    def stop(self, reason: str) -> None:
        """End Bridge, once, for `reason`."""
        if not self.stopped.is_set():
            self.reason = reason
            self.stopped.set()
            emit("proton_bridge.stopped", epoch=self._cfg.epoch, reason=reason)
        self._kill()

    def _raise_if_stopped(self) -> None:
        if self.stopped.is_set():
            raise Stopped

    def _kill(self) -> None:
        process, self._process = self._process, None
        if process is not None:
            process.kill()

    def before(self) -> None:
        """Write back anything Bridge changed, before the caller goes on."""
        with self.turn():
            pass

    def on_event(self, event: UserEvent) -> None:
        """Relay what Bridge reported, after writing back its vault; the callback `watch` is given."""
        try:
            with self.turn():
                self._relay(event)
        except Stopped:
            pass

    def _relay(self, event: UserEvent) -> None:
        if event.sync == "finished":
            self._synced.add(event.user_id)
        elif event.sync == "started":
            self._synced.discard(event.user_id)
        try:
            self._app.event(event.user_id, event.state, event.sync, event.progress)
        except Refused:
            self.stop("event_refused")
        except AppUnreachable:
            pass

    def _certificate_fingerprint(self) -> str | None:
        """SHA-256 (hex) of the certificate Bridge serves IMAP and SMTP under, or None when it cannot be read."""
        directory = self._cfg.home / "certs"
        directory.mkdir(exist_ok=True)
        try:
            assert self._link is not None
            self._link.export_certificate(str(directory))
            der = ssl.PEM_cert_to_DER_cert((directory / "cert.pem").read_text())
        except (BridgeError, OSError, ValueError):
            return None
        return hashlib.sha256(der).hexdigest()

    def login(self, username: str, password: str) -> dict[str, Any]:
        self.before()
        link = self._bridge()
        if self._pending_login:
            with contextlib.suppress(BridgeError):
                link.abort(self._pending_login)
        self._pending_login = username
        return self._answer(link.login(username, password))

    def verified_login(self, password: str) -> dict[str, Any]:
        """Retry the pending login after the person passed Proton's human check; nothing is aborted first, for Bridge keeps
        the check's details with the login it is holding."""
        self.before()
        return self._answer(self._bridge().login(self._pending_login, password, verified=True))

    def second_factor(self, code: str) -> dict[str, Any]:
        self.before()
        return self._answer(self._bridge().second_factor(self._pending_login, code))

    def mailbox_password(self, password: str) -> dict[str, Any]:
        self.before()
        return self._answer(self._bridge().mailbox_password(self._pending_login, password))

    def forget(self, user_id: str) -> dict[str, Any]:
        self.before()
        self._bridge().remove(user_id)
        self.before()
        return {}

    def _bridge(self) -> BridgeLink:
        if self._link is None or self.stopped.is_set():
            raise Stopped
        return self._link

    def _answer(self, event: LoginEvent) -> dict[str, Any]:
        """The wire answer for what Bridge said to a login step; on `finished`, the account once its session is stored."""
        if event.kind == "tfa":
            return {"step": "two_factor"}
        if event.kind == "two_passwords":
            return {"step": "mailbox_password"}
        if event.kind == "human_verification":
            return {"step": "human_verification", "url": event.url}
        if event.kind == "error":
            if event.reason == "security_key":
                with contextlib.suppress(BridgeError):
                    self._bridge().abort(self._pending_login)
            self._pending_login = ""
            return {"step": "refused", "reason": event.reason}
        link = self._bridge()
        user = link.user(event.user_id)
        if not user.split:
            link.set_split(user.id, True)
            user = link.user(user.id)
        self._pending_login = ""
        self.before()
        return {"step": "connected", "user_id": user.id, "addresses": list(user.addresses),
                "bridge_password": user.password, "epoch": self._cfg.epoch, "synced": user.id in self._synced}


def main(env: Mapping[str, str] = os.environ) -> int:
    """The pod's entry point: configure from the environment (`ashley.mail.proton_pod` lists it), start the relays and the
    control port, then keep Bridge until it must end."""
    import keeper_process
    import keeper_relay
    import keeper_serve
    config = Config(int(env["BRIDGE_EPOCH"]), float(env["BRIDGE_HEARTBEAT_S"]), float(env["BRIDGE_FENCE_S"]),
                    Path(env["HOME"]))
    app = AppClient(env["ASHLEY_URL"], config.epoch, env["BRIDGE_TOKEN"], timeout_s=min(10.0, config.fence_s / 3))
    keeper = Keeper(config, app, _command(config.home), lambda: keeper_process.start(config.home))
    relays = [keeper_relay.Relay(int(env["BRIDGE_IMAP_PORT"]), 1143, keeper.before),
              keeper_relay.Relay(int(env["BRIDGE_SMTP_PORT"]), 1025, keeper.before)]

    def terminate(signum: int, frame: object) -> None:
        keeper.stop("terminated")

    signal.signal(signal.SIGTERM, terminate)
    server = keeper_serve.serve(keeper, env["BRIDGE_TOKEN"], int(env["BRIDGE_CONTROL_PORT"]),
                                tls=keeper_serve.server_context(env["BRIDGE_TLS_DIR"]))
    for target in (*(r.serve for r in relays), server.serve_forever):
        threading.Thread(target=target, daemon=True).start()
    return keeper.run()


def _command(home: Path) -> keeper_files.Runner:
    def run(argv: Sequence[str]) -> None:
        subprocess.run(list(argv), check=True, env={"HOME": str(home), "PATH": "/usr/bin:/bin"},
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    return run
