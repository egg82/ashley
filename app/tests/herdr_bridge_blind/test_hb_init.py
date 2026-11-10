"""`init` with the real openssl: the settings, the certificate and the one-time token."""

import hashlib
import socket
import ssl
from pathlib import Path

from herdr_bridge.config import Config, load
from herdr_bridge.install import init
from herdr_bridge_blind_pki import Pki, der_fingerprint
from herdr_bridge_blind_support import build_bridge
from herdr_bridge_blind_tls import client_context, serving


def test_init_writes_a_config_that_loads_back_and_a_cert_that_matches_the_fingerprint(tmp_path: Path, pki: Pki) -> None:
    (tmp_path / "ca.pem").write_bytes(pki.ca.cert_pem)
    state = tmp_path / "state"
    state.mkdir()
    config = Config("127.0.0.1", 0, (str(tmp_path),), str(state), str(tmp_path / "ca.pem"))
    cfg_path = tmp_path / "config.json"
    token, fingerprint = init(config, cfg_path)
    assert load(cfg_path) == config
    assert fingerprint == der_fingerprint(config.cert.read_bytes())
    assert len(token) >= 32
    assert config.key.exists()
    assert token.encode() not in cfg_path.read_bytes()
    again_token, again_fingerprint = init(config, cfg_path)
    assert again_token != token
    assert again_fingerprint == fingerprint


def test_a_bridge_set_up_by_the_real_init_presents_that_certificate(tmp_path: Path, pki: Pki) -> None:
    b = build_bridge(tmp_path, pki)
    token, fingerprint = init(b.config, b.config_path)
    b.herdr.calls.clear()
    with serving(b) as port:
        ctx = client_context(tmp_path, pki.client)
        with socket.create_connection(("127.0.0.1", port), timeout=5) as raw, ctx.wrap_socket(raw) as tls:
            der = tls.getpeercert(binary_form=True)
            assert isinstance(tls, ssl.SSLSocket)
    assert der is not None
    assert hashlib.sha256(der).hexdigest() == fingerprint
    assert token != b.token


def test_init_leaves_the_private_key_readable_by_its_owner_alone(tmp_path: Path, pki: Pki) -> None:
    (tmp_path / "ca.pem").write_bytes(pki.ca.cert_pem)
    state = tmp_path / "state"
    config = Config("127.0.0.1", 0, (str(tmp_path),), str(state), str(tmp_path / "ca.pem"))

    def careless(cert: Path, key: Path) -> None:
        cert.write_bytes(pki.server.cert_pem)
        key.write_bytes(pki.server.key_pem)
        key.chmod(0o644)

    init(config, tmp_path / "config.json", careless)
    assert config.key.stat().st_mode & 0o077 == 0
