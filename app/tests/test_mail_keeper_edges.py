"""The keeper's two edges, over real sockets: its control port (bearer token, routes, and what each failure is) and the
relay to Bridge's loopback; and its calls to the app over real HTTP (`keeper_app.urllib_transport`)."""

import json
import socket
import threading
from collections.abc import Generator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import httpx2
import pytest
from keeper_app import AppClient, AppUnreachable, Refused
from keeper_link import BridgeError, LoginEvent, UserInfo
from keeper_relay import Relay
from keeper_serve import serve
from mail_keeper_support import TOKEN, Rig, make_keychain, rig, FakeApp


@pytest.fixture
def running(tmp_path: Path) -> Generator[tuple[Rig, str]]:
    made = tmp_path / "earlier"
    made.mkdir()
    r = rig(tmp_path / "home", FakeApp(1, b"v", make_keychain(made)))
    r.home.mkdir()
    r.keeper.boot()
    server = serve(r.keeper, TOKEN, 0, "127.0.0.1")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield r, f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def post(base: str, path: str, body: dict[str, Any], token: str = TOKEN) -> httpx2.Response:
    return httpx2.post(base + path, json=body, headers={"Authorization": f"Bearer {token}"}, timeout=5)


def test_the_control_port_answers_each_login_step_and_only_to_the_epochs_token(running: tuple[Rig, str]) -> None:
    r, base = running
    r.bridge.logins = [LoginEvent("tfa"), LoginEvent("two_passwords"), LoginEvent("error", reason="code")]
    assert post(base, "/login", {"username": "a", "password": "b"}).json() == {"step": "two_factor"}
    assert post(base, "/login/two-factor", {"code": "1"}).json() == {"step": "mailbox_password"}
    assert post(base, "/login/mailbox-password", {"password": "p"}).json() == {"step": "refused", "reason": "code"}
    assert post(base, "/login", {"username": "a", "password": "b"}, token="other").status_code == 401
    assert httpx2.post(base + "/login", json={}, timeout=5).status_code == 401
    assert post(base, "/nowhere", {}).status_code == 404
    assert post(base, "/login", {"username": "a"}).status_code == 400
    r.bridge.logins = [LoginEvent("human_verification", url="https://verify.proton.me/?t=1"), LoginEvent("tfa")]
    assert post(base, "/login", {"username": "a", "password": "b"}).json() == {
        "step": "human_verification", "url": "https://verify.proton.me/?t=1"}
    assert post(base, "/login/verified", {"password": "b"}).json() == {"step": "two_factor"}
    assert post(base, "/login/verified", {}).status_code == 400


def test_the_control_port_forgets_a_user_and_says_503_once_bridge_has_ended_and_502_when_it_cannot_be_asked(
        running: tuple[Rig, str]) -> None:
    r, base = running
    r.bridge.users_held["u1"] = UserInfo("u1", "connected", True, (), "pw")
    assert post(base, "/forget", {"user_id": "u1"}).status_code == 200 and not r.bridge.users_held

    def gone() -> None:
        raise BridgeError("gone")

    r.bridge.on_login = gone
    assert post(base, "/login", {"username": "a", "password": "b"}).status_code == 502
    r.keeper.stop("fence")
    assert post(base, "/login", {"username": "a", "password": "b"}).status_code == 503


def test_the_relay_copies_both_ways_and_is_a_turn_of_the_keeper_per_connection() -> None:
    echo = socket.create_server(("127.0.0.1", 0))
    seen: list[str] = []

    def serve_echo() -> None:
        while True:
            try:
                conn, _ = echo.accept()
            except OSError:
                return
            conn.sendall(conn.recv(100).upper())
            conn.close()

    threading.Thread(target=serve_echo, daemon=True).start()
    relay = Relay(0, echo.getsockname()[1], lambda: seen.append("turn"), "127.0.0.1")
    threading.Thread(target=relay.serve, daemon=True).start()
    for _ in range(2):
        with socket.create_connection(("127.0.0.1", relay.port), timeout=5) as client:
            client.sendall(b"a001 noop")
            assert client.recv(100) == b"A001 NOOP"
    relay.close()
    echo.close()
    assert seen == ["turn", "turn"]


class _App(BaseHTTPRequestHandler):
    status = 200
    heard: list[tuple[str, str, str, Any]] = []

    def _go(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length)) if length else None
        _App.heard.append((self.command, self.path, self.headers["Authorization"], body))
        data = json.dumps({"generation": 7, "vault": None, "keychain": None}).encode()
        self.send_response(_App.status)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    do_GET = do_PUT = do_POST = _go

    def log_message(self, format: str, *args: Any) -> None:
        pass


def test_the_app_client_sends_the_epoch_the_token_and_base64_and_tells_a_refusal_from_silence() -> None:
    _App.heard, _App.status = [], 200
    server = ThreadingHTTPServer(("127.0.0.1", 0), _App)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    app = AppClient(f"http://127.0.0.1:{server.server_address[1]}/", 3, "tok", 5.0)
    try:
        assert app.fetch_vault().generation == 7
        assert app.write_back(7, b"\x00vault", b"keys") == 7
        app.heartbeat(None)
        assert _App.heard[0][:3] == ("GET", "/api/mail-bridge/keeper/vault?epoch=3", "Bearer tok")
        assert _App.heard[1][3] == {"epoch": 3, "generation": 7, "vault": "AHZhdWx0", "keychain": "a2V5cw=="}
        assert _App.heard[2][3] == {"epoch": 3, "certificate_sha256": None}
        _App.status = 409
        with pytest.raises(Refused) as refused:
            app.heartbeat(None)
        assert refused.value.status == 409
    finally:
        server.shutdown()
        server.server_close()
    with pytest.raises(AppUnreachable):
        app.heartbeat(None)
