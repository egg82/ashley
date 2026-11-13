"""The real server over real TLS: a client certificate from the configured CA is required, TLS 1.3 only."""

import hashlib
import http.client
import json
import ssl
from collections.abc import Generator
from dataclasses import dataclass

import pytest

from herdr_bridge_support import PERSON, TOKEN, FakeHerdr, Issued, ca_with_client, ok, serving


@dataclass
class Running:
    port: int
    client: Issued
    rogue: Issued
    pin: str
    log: list[str]

    def connect(self, cert: Issued | None, version: ssl.TLSVersion = ssl.TLSVersion.TLSv1_3) -> http.client.HTTPSConnection:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE  # the app pins the fingerprint instead of trusting a CA
        ctx.minimum_version = ctx.maximum_version = version
        if cert is not None:
            ctx.load_cert_chain(cert.cert, cert.key)
        return http.client.HTTPSConnection("127.0.0.1", self.port, context=ctx, timeout=5)

    def whoami(self, cert: Issued | None, version: ssl.TLSVersion = ssl.TLSVersion.TLSv1_3) -> tuple[int, object, bytes | None]:
        conn = self.connect(cert, version)
        conn.connect()
        sock = conn.sock
        seen = sock.getpeercert(binary_form=True) if isinstance(sock, ssl.SSLSocket) else None
        conn.request("GET", "/v1/whoami", headers={"Authorization": f"Bearer {TOKEN}", "X-Ashley-Person": PERSON})
        res = conn.getresponse()
        return res.status, json.loads(res.read()), seen


@pytest.fixture(scope="module")
def running(tmp_path_factory: pytest.TempPathFactory) -> Generator[Running]:
    root = tmp_path_factory.mktemp("tls")
    ca, client = ca_with_client(root, "good")
    _, rogue = ca_with_client(root, "rogue")
    with serving(root, ca, FakeHerdr({("--version",): ok("version.out")})) as served:
        yield Running(served.port, client, rogue, served.pin, served.bridge.log.lines)


def test_a_client_with_a_certificate_from_the_configured_ca_is_served(running: Running) -> None:
    status, body, seen = running.whoami(running.client)
    assert status == 200 and body == {"bridge_version": "0.4.0", "herdr_version": "0.9.5", "person": PERSON,
                                  "capabilities": ["files"]}
    assert seen is not None and hashlib.sha256(seen).hexdigest() == running.pin, "the certificate the client sees is the one init would pin"


@pytest.mark.parametrize("who", ["none", "rogue_ca"])
def test_a_client_without_a_certificate_from_that_ca_gets_no_answer(running: Running, who: str) -> None:
    with pytest.raises((OSError, http.client.HTTPException)):
        running.whoami(None if who == "none" else running.rogue)


def test_tls_1_2_is_refused(running: Running) -> None:
    with pytest.raises((OSError, http.client.HTTPException)):
        running.whoami(running.client, ssl.TLSVersion.TLSv1_2)


def test_a_refused_handshake_is_logged_without_an_address_and_the_server_keeps_serving(running: Running) -> None:
    with pytest.raises((OSError, http.client.HTTPException)):
        running.whoami(None)
    assert running.whoami(running.client)[0] == 200
    refused = [line for line in running.log if line.startswith("call=connection status=failed")]
    assert refused and not any("127.0.0.1" in line for line in running.log)
