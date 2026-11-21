"""Sealing a connection's secret at rest: AES-256-GCM under the app's current key (`CONNECTIONS_KEY`, kept in the
deployment's secret store), which can open under one more (`CONNECTIONS_KEY_OPENS`) while a rotation runs
(`ashley.connections.reseal`). A sealed value is one version byte naming the key, a 12-byte random nonce, then the
ciphertext with its tag. The associated data binds it to its row's household and kind, so a sealed value copied to
another row does not open."""

import base64
import binascii
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

VERSION = 1
"""The version of a key written with no `N:` prefix: the key every sealed value was made under before a rotation."""

_NONCE = 12

VAULT_BOUND = b"proton_bridge:vault"
KEYCHAIN_BOUND = b"proton_bridge:keychain"
KEEPER_BOUND = b"proton_bridge:keeper"
"""What Proton Bridge's one row's three sealed columns are bound to, so one does not open as another."""


class Unsealable(Exception):
    """A sealed value that this key cannot open: another key's version, another row's, or altered."""


def key_from(text: str) -> bytes:
    """The 32-byte key that `text`, standard base64, holds. Raises ValueError for anything else."""
    try:
        key = base64.b64decode(text.strip(), validate=True)
    except (binascii.Error, ValueError) as e:
        raise ValueError("CONNECTIONS_KEY is not base64") from e
    if len(key) != 32:
        raise ValueError("CONNECTIONS_KEY is not 32 bytes")
    return key


def versioned_key(text: str) -> tuple[int, bytes]:
    """The version and 32-byte key that `text` holds: `N:` and the base64 (N from 1 to 255), or the base64 alone, which
    is `VERSION`. Raises ValueError for anything else, its message never holding the text."""
    head, colon, rest = text.strip().partition(":")
    if not colon:
        return VERSION, key_from(head)
    if not head.isdigit() or not 1 <= int(head) <= 255:
        raise ValueError("a connections key's version is a number from 1 to 255")
    return int(head), key_from(rest)


def sealer_of(current: str, opens: str = "") -> "Sealer":
    """The sealer for the `CONNECTIONS_KEY` text `current` and the optional `CONNECTIONS_KEY_OPENS` text `opens`, which
    is opened but never sealed under. Raises ValueError for a key that does not parse or two that share a version."""
    version, key = versioned_key(current)
    keys = {version: key}
    if opens.strip():
        other, other_key = versioned_key(opens)
        if other == version:
            raise ValueError("CONNECTIONS_KEY and CONNECTIONS_KEY_OPENS have the same version")
        keys[other] = other_key
    return Sealer(keys, current=version)


def bound_to(household_id: int, kind: str, person_id: int | None = None) -> bytes:
    """The associated data a row's secret is sealed with: a personal connection's names its person too."""
    suffix = "" if person_id is None else f":{person_id}"
    return f"connection:{household_id}:{kind}{suffix}".encode()


class Sealer:
    def __init__(self, keys: dict[int, bytes], current: int = VERSION) -> None:
        """`keys` by version; `current` is the one new values are sealed under, and must be among them."""
        if current not in keys or not all(1 <= v <= 255 for v in keys):
            raise ValueError("the current key version has no key")
        self._keys = {v: AESGCM(k) for v, k in keys.items()}
        self._current = current

    @property
    def current(self) -> int:
        """The version `seal` writes."""
        return self._current

    def seal(self, secret: str, bound: bytes) -> bytes:
        nonce = os.urandom(_NONCE)
        return bytes([self._current]) + nonce + self._keys[self._current].encrypt(nonce, secret.encode(), bound)

    def open(self, sealed: bytes, bound: bytes) -> str:
        """Raises Unsealable."""
        if len(sealed) < 1 + _NONCE + 16 or sealed[0] not in self._keys:
            raise Unsealable("unknown key version or too short")
        nonce, body = sealed[1:1 + _NONCE], sealed[1 + _NONCE:]
        try:
            return self._keys[sealed[0]].decrypt(nonce, body, bound).decode()
        except (InvalidTag, UnicodeDecodeError) as e:
            raise Unsealable("does not open under this key") from e
