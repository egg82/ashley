"""`herdr-bridge init` and the settings file."""

import json
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from herdr_bridge.auth import PERSON_FILE, TOKEN_FILE, Auth, token_digest
from herdr_bridge.config import Config, ConfigError, load
from herdr_bridge.errors import BridgeError
from herdr_bridge.jsonget import obj
from herdr_bridge.install import fingerprint, init, openssl_args

import datetime


def make_cert(cert: Path, key: Path) -> None:
    k = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "t")])
    now = datetime.datetime.now(datetime.timezone.utc)
    c = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(k.public_key())
         .serial_number(x509.random_serial_number()).not_valid_before(now).not_valid_after(now + datetime.timedelta(days=1))
         .sign(k, hashes.SHA256()))
    cert.write_bytes(c.public_bytes(serialization.Encoding.PEM))
    key.write_bytes(k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))


def config(tmp_path: Path) -> Config:
    ca = tmp_path / "ca.pem"
    ca.write_text("x")
    return Config("127.0.0.1", 0, ("/srv",), str(tmp_path / "state"), str(ca))


def test_init_keeps_only_the_tokens_digest_and_prints_it_once(tmp_path: Path) -> None:
    cfg = config(tmp_path)
    token, pin = init(cfg, tmp_path / "config.json", make_cert)
    state = tmp_path / "state"
    assert (state / TOKEN_FILE).read_text().strip() == token_digest(token)
    assert token not in "".join(p.read_text() for p in state.rglob("*") if p.is_file() and p.suffix != ".pem") + (
        tmp_path / "config.json").read_text()
    assert pin == fingerprint(cfg.cert) and len(pin) == 64
    assert (cfg.key.stat().st_mode & 0o777) == 0o600


def test_init_again_mints_a_new_token_keeps_the_certificate_and_releases_the_person(tmp_path: Path) -> None:
    cfg = config(tmp_path)
    first, pin = init(cfg, tmp_path / "config.json", make_cert)
    Auth(tmp_path / "state").check(f"Bearer {first}", "7")
    assert (tmp_path / "state" / PERSON_FILE).exists()
    second, pin2 = init(cfg, tmp_path / "config.json", make_cert)
    assert second != first and pin2 == pin
    auth = Auth(tmp_path / "state")
    with pytest.raises(BridgeError):
        auth.check(f"Bearer {first}", "7")
    assert auth.check(f"Bearer {second}", "8") == "8"


def test_the_settings_round_trip_and_roots_must_be_absolute(tmp_path: Path) -> None:
    cfg = config(tmp_path)
    path = tmp_path / "config.json"
    cfg.dump(path)
    assert load(path) == cfg
    raw = obj(json.loads(path.read_text()))
    cases: list[dict[str, object]] = [{**raw, "roots": []}, {**raw, "roots": ["relative"]},
                                      {**raw, "client_ca": str(tmp_path / "gone")}, {"port": 1}, {**raw, "extra": 1}]
    for broken in cases:
        path.write_text(json.dumps(broken))
        with pytest.raises(ConfigError):
            load(path)
    path.write_text("not json")
    with pytest.raises(ConfigError):
        load(path)


def test_the_certificate_is_made_by_openssl_with_an_ec_key_and_no_passphrase() -> None:
    args = openssl_args(Path("/c.pem"), Path("/k.pem"))
    assert args[:3] == ["openssl", "req", "-x509"] and "-nodes" in args and "ec" in args
    assert args[args.index("-keyout") + 1] == "/k.pem" and args[args.index("-out") + 1] == "/c.pem"
