"""Web push's tunables, as data in `push.json` beside this module, and her VAPID identity from the settings.

A notification's title is `title` and its body the reply's text cut to `body_chars`; one that carries only receipts
(a spoken turn's, which the speaker's phone shows) has `done_title` or, when a call waits, `held_title`, and the
headlines for a body; a push service holds one for an
offline browser at most `ttl_s`, and a send waits at most `timeout_s`. The server POSTs to whatever endpoint a browser
subscribes, so only the browsers' own push services are accepted: an https URL on the default port, with no user info,
whose host is one of `hosts` or ends with one of `domains`."""

import base64
import json
import logging
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from ... import logs
from ...settings import Settings

FILE = Path(__file__).with_name("push.json")
log = logging.getLogger("ashley.channels.push")


@dataclass(frozen=True)
class Config:
    title: str
    done_title: str
    held_title: str
    body_chars: int
    ttl_s: int
    timeout_s: float
    hosts: tuple[str, ...]
    domains: tuple[str, ...]

    def __post_init__(self) -> None:
        if not all(t.strip() for t in (self.title, self.done_title, self.held_title)) or self.body_chars < 1 or self.ttl_s < 1 or self.timeout_s <= 0:
            raise ValueError("push.json needs a title and positive limits")
        if not self.hosts or not all(d.startswith(".") for d in self.domains):
            raise ValueError("push.json needs hosts, and each domain starts with a dot")


def parse(raw: dict[str, Any]) -> Config:
    """A Config from the decoded JSON. Raises ValueError naming a key that is missing or unknown."""
    expected = {f.name for f in fields(Config)}
    if set(raw) != expected:
        raise ValueError(f"push.json keys: missing {sorted(expected - set(raw))}, unknown {sorted(set(raw) - expected)}")
    return Config(str(raw["title"]), str(raw["done_title"]), str(raw["held_title"]), int(raw["body_chars"]), int(raw["ttl_s"]), float(raw["timeout_s"]),
                  tuple(map(str, raw["hosts"])), tuple(map(str, raw["domains"])))


def load(path: Path = FILE) -> Config:
    return parse(json.loads(path.read_text(encoding="utf-8")))


def is_push_service(endpoint: str, config: Config) -> bool:
    """Whether `endpoint` is a URL on one of the browsers' push services (the module docstring)."""
    try:
        url = urlsplit(endpoint)
        port = url.port
    except ValueError:
        return False
    host = url.hostname or ""
    return (url.scheme == "https" and url.username is None and url.password is None and port in (None, 443)
            and (host in config.hosts or host.endswith(config.domains)))


@dataclass(frozen=True)
class Vapid:
    """Her Web Push identity: the public key a browser subscribes with (base64url, an uncompressed P-256 point), the
    private key that signs each send (base64url, raw or DER), and the contact a push service may write to."""

    public_key: str
    private_key: str
    subject: str


def vapid(settings: Settings) -> Vapid | None:
    """Her identity when all three settings are set and the keys are one P-256 pair; None otherwise, and push is off."""
    found = Vapid(settings.vapid_public_key, settings.vapid_private_key, settings.vapid_subject)
    if not all((found.public_key, found.private_key, found.subject)):
        return None
    try:
        private = _private(_unb64(found.private_key))
        public = private.public_key().public_bytes(serialization.Encoding.X962,
                                                   serialization.PublicFormat.UncompressedPoint)
        matches = public == _unb64(found.public_key)
    except (ValueError, TypeError):
        return None
    return found if matches else None


def checked(settings: Settings) -> Vapid | None:
    """`vapid`, logging `push.config_bad` when the settings name an identity that is not usable: some of the three
    missing, or keys that are not one P-256 pair. Never the keys."""
    found = vapid(settings)
    if found is None and any((settings.vapid_public_key, settings.vapid_private_key, settings.vapid_subject)):
        logs.warning(log, "push.config_bad", push="off")
    return found


def _private(raw: bytes) -> ec.EllipticCurvePrivateKey:
    if len(raw) == 32:
        return ec.derive_private_key(int.from_bytes(raw, "big"), ec.SECP256R1())
    key = serialization.load_der_private_key(raw, password=None)
    if not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(key.curve, ec.SECP256R1):
        raise ValueError("not a P-256 key")
    return key


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
