"""`herdr-bridge init`: write the settings, make the certificate if there is none, and mint the token, which is printed
once and kept only as a digest. Running it again mints a new token and releases the person lock."""

import secrets
import ssl
import subprocess
from collections.abc import Callable
from hashlib import sha256
from pathlib import Path

from .auth import PERSON_FILE, TOKEN_FILE, token_digest
from .config import Config

CertMaker = Callable[[Path, Path], None]


def openssl_args(cert: Path, key: Path) -> list[str]:
    return [
        "openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1", "-nodes",
        "-days", "3650", "-subj", "/CN=ashley-herdr-bridge", "-keyout", str(key), "-out", str(cert),
    ]


def openssl_cert(cert: Path, key: Path) -> None:
    subprocess.run(openssl_args(cert, key), check=True, capture_output=True)


def fingerprint(cert: Path) -> str:
    """sha256 of the DER certificate in lowercase hex: what the app pins."""
    return sha256(ssl.PEM_cert_to_DER_cert(cert.read_text())).hexdigest()


def init(config: Config, config_path: Path, make_cert: CertMaker = openssl_cert) -> tuple[str, str]:
    """(token, certificate fingerprint). The token is returned for printing and stored nowhere."""
    state = Path(config.state_dir)
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    config.cert.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not config.cert.exists() or not config.key.exists():
        make_cert(config.cert, config.key)
        config.key.chmod(0o600)
    token = secrets.token_urlsafe(32)
    (state / TOKEN_FILE).write_text(token_digest(token) + "\n")
    (state / PERSON_FILE).unlink(missing_ok=True)
    config.dump(config_path)
    return token, fingerprint(config.cert)
