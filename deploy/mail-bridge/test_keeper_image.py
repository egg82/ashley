"""The keeper against a real Bridge, in the image it ships in (CI's mail bridge image job): with a stand-in for the
app's keeper routes in this process, the first start writes the vault back at generation 0, and once the app stops
answering Bridge and the pod's process are gone within `fence_s`; a heartbeat the app refuses ends them at once. No Proton
account is involved: Bridge runs with no user.

    python -m unittest discover -v -s /test      (as the pod runs: uid 1000, read-only root, HOME and /tmp writable)"""

import base64
import json
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

TOKEN = "image-test-token"
FENCE_S = 8
ENTRY = "import keeper; raise SystemExit(keeper.main())"


class App:
    """The app's keeper routes: the vault in memory, heartbeats counted, and a refusal on demand."""

    generation = 0
    vault: bytes | None = None
    keychain: bytes | None = None
    beats = 0
    refuse_heartbeat = False


def handler(app: type[App]) -> type[BaseHTTPRequestHandler]:
    class Routes(BaseHTTPRequestHandler):
        def _answer(self, status: int, body: dict[str, Any] | None) -> None:
            data = json.dumps(body or {}).encode()
            self.send_response(status)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _route(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            body: dict[str, Any] = json.loads(self.rfile.read(length)) if length else {}
            if self.headers.get("Authorization") != f"Bearer {TOKEN}":
                return self._answer(401, None)
            path = self.path.split("?")[0].rsplit("/", 1)[-1]
            if path == "vault" and self.command == "GET":
                enc = base64.b64encode
                return self._answer(200, {"generation": app.generation,
                                          "vault": None if app.vault is None else enc(app.vault).decode(),
                                          "keychain": None if app.keychain is None else enc(app.keychain).decode()})
            if path == "vault":
                if body["generation"] != app.generation:
                    return self._answer(409, None)
                app.generation += 1
                app.vault, app.keychain = base64.b64decode(body["vault"]), base64.b64decode(body["keychain"])
                return self._answer(200, {"generation": app.generation})
            if path == "heartbeat":
                if app.refuse_heartbeat:
                    return self._answer(409, None)
                app.beats += 1
            return self._answer(200, {"applied": True})

        do_GET = do_PUT = do_POST = _route

        def log_message(self, format: str, *args: Any) -> None:
            pass

    return Routes


def bridge_processes() -> list[str]:
    found: list[str] = []
    for entry in Path("/proc").iterdir():
        if entry.name.isdigit():
            try:
                found.append((entry / "cmdline").read_bytes().decode(errors="replace"))
            except OSError:
                pass
    return [c for c in found if "protonmail/bridge/bridge" in c]


def wait(condition: Callable[[], bool], seconds: float) -> bool:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if condition():
            return True
        time.sleep(0.25)
    return False


class KeeperWithRealBridge(unittest.TestCase):
    def start(self, fresh: bool = True, epoch: int = 1) -> subprocess.Popen[bytes]:
        if fresh:
            App.generation, App.vault, App.keychain = 0, None, None
        App.beats, App.refuse_heartbeat = 0, False
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler(App))
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        home = tempfile.mkdtemp(prefix="home")
        tls = tempfile.mkdtemp(prefix="tls")
        subprocess.run(["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1", "-nodes",
                        "-keyout", f"{tls}/tls.key", "-out", f"{tls}/tls.crt", "-subj", "/CN=keeper", "-days", "1"],
                       check=True, capture_output=True)
        env = {"HOME": home, "PATH": "/usr/bin:/bin", "ASHLEY_URL": f"http://127.0.0.1:{self.server.server_address[1]}",
               "BRIDGE_EPOCH": str(epoch), "BRIDGE_TOKEN": TOKEN, "BRIDGE_HEARTBEAT_S": "1", "BRIDGE_FENCE_S": str(FENCE_S),
               "BRIDGE_CONTROL_PORT": "18080", "BRIDGE_TLS_DIR": tls, "BRIDGE_IMAP_PORT": "12143", "BRIDGE_SMTP_PORT": "12025"}
        process = subprocess.Popen([sys.executable, "-c", ENTRY], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.addCleanup(process.kill)
        self.addCleanup(self.server.server_close)
        self.assertTrue(wait(lambda: App.generation >= 1 and App.beats >= 1, 150), "no first write-back and heartbeat")
        return process

    def test_the_first_vault_is_written_back_and_a_cut_off_keeper_ends_bridge_within_the_fence(self) -> None:
        process = self.start()
        self.assertTrue(bridge_processes() and App.vault)
        self.server.shutdown()
        self.server.socket.close()
        cut = time.monotonic()
        self.assertTrue(wait(lambda: process.poll() is not None, FENCE_S + 6), "the keeper outlived its fence")
        self.assertLess(time.monotonic() - cut, FENCE_S + 6)
        self.assertEqual(process.returncode, 1)
        self.assertFalse(bridge_processes(), "Bridge outlived the keeper")

    def test_a_second_pod_opens_the_vault_the_first_wrote_back_and_writes_back_the_rewrite_of_its_start(self) -> None:
        first = self.start()
        written = App.generation
        first.kill()
        first.wait()
        self.server.shutdown()
        self.assertTrue(wait(lambda: not bridge_processes(), 10))
        second = self.start(fresh=False, epoch=2)
        self.assertTrue(wait(lambda: App.generation > written, 60), "the start's rewrite of the vault was not written back")
        self.assertIsNone(second.poll(), "the second keeper ended")

    def test_a_refused_heartbeat_ends_bridge_at_once(self) -> None:
        process = self.start()
        App.refuse_heartbeat = True
        self.assertTrue(wait(lambda: process.poll() is not None, 5), "a refused heartbeat did not end the keeper")
        self.assertFalse(bridge_processes())
        self.server.shutdown()


if __name__ == "__main__":
    unittest.main()
