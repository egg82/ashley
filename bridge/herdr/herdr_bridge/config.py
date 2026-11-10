"""The bridge's settings file, written by `herdr-bridge init` and read by `serve`."""

import json
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from .jsonget import integer, obj, strings, text

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "ashley-herdr-bridge"
STATE_DIR = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) / "ashley-herdr-bridge"


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Config:
    host: str
    port: int
    roots: tuple[str, ...]  # directories under which a session may be started
    state_dir: str  # token digest, the recorded person, the certificate and key
    client_ca: str  # the `ashley-bridges` CA certificate: the only issuer of client certificates this bridge accepts
    herdr: str = "herdr"
    start_timeout_ms: int = 90_000
    max_file_bytes: int = 26_214_400  # the most one transferred file may hold, either direction
    max_files: int = 32  # the most files `in/` or `out/` may hold
    keep_job_dirs: int = 20  # the newest job folders (`<root>/ashley-jobs/j<id>`) kept; older ones are removed at a start

    @property
    def cert(self) -> Path:
        return Path(self.state_dir) / "tls" / "cert.pem"

    @property
    def key(self) -> Path:
        return Path(self.state_dir) / "tls" / "key.pem"

    def dump(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({**asdict(self), "roots": list(self.roots)}, indent=2) + "\n")


FIELDS = {f.name for f in fields(Config)}


def load(path: Path) -> Config:
    try:
        raw = obj(json.loads(path.read_text()))
    except (OSError, ValueError) as e:
        raise ConfigError(f"cannot read {path}: {type(e).__name__}") from e
    roots = strings(raw.get("roots"))
    host, state_dir, client_ca = text(raw, "host"), text(raw, "state_dir"), text(raw, "client_ca")
    port = integer(raw, "port")
    if not roots or not all(os.path.isabs(r) for r in roots):
        raise ConfigError("roots must be a non-empty list of absolute directories")
    if host is None or port is None or state_dir is None or client_ca is None or set(raw) - FIELDS:
        raise ConfigError(f"{path} must hold exactly: {', '.join(sorted(FIELDS))}")
    if not Path(client_ca).is_file():
        raise ConfigError("client_ca is not a file: the bridge accepts no client without the ashley-bridges CA")
    return Config(host, port, tuple(roots), state_dir, client_ca,
                  text(raw, "herdr") or "herdr", integer(raw, "start_timeout_ms") or 90_000,
                  integer(raw, "max_file_bytes") or 26_214_400, integer(raw, "max_files") or 32,
                  integer(raw, "keep_job_dirs") or 20)
