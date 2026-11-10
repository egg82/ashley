"""Sealing a connection's secret at rest: AES-256-GCM under the app's one key (`CONNECTIONS_KEY`, kept in the
deployment's secret store). A sealed value is one version byte naming the key, a 12-byte random nonce, then the
ciphertext with its tag. The associated data binds it to its row's household and kind, so a sealed value copied to
another row does not open."""

import base64
import binascii
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

VERSION = 1
"""The version byte today's key seals under. A rotation gives the new key the next version and keeps the old one
for opening until every row is sealed again."""

_NONCE = 12


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


def bound_to(household_id: int, kind: str, person_id: int | None = None) -> bytes:
    """The associated data a row's secret is sealed with: a personal connection's names its person too."""
    suffix = "" if person_id is None else f":{person_id}"
    return f"connection:{household_id}:{kind}{suffix}".encode()


class Sealer:
    def __init__(self, keys: dict[int, bytes], current: int = VERSION) -> None:
        """`keys` by version; `current` is the one new values are sealed under, and must be among them."""
        if current not in keys:
            raise ValueError("the current key version has no key")
        self._keys = {v: AESGCM(k) for v, k in keys.items()}
        self._current = current

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
