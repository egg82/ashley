"""Sealing a connection's secret (`connections.sealing`): it opens under its key and its row's binding only; the stored
form starts with its key's version and never holds the secret; anything altered, another row's, another key's or
another version's does not open; a key setting that is not base64 of 32 bytes is refused."""

import base64
import os

import pytest
from ashley.connections.sealing import VERSION, Sealer, Unsealable, bound_to, key_from

KEY = os.urandom(32)
SECRET = "the-households-test-key"
HERE = bound_to(10, "sure")


def test_a_sealed_secret_opens_under_its_key_and_binding() -> None:
    sealer = Sealer({VERSION: KEY})
    sealed = sealer.seal(SECRET, HERE)
    assert sealed[0] == VERSION
    assert SECRET.encode() not in sealed
    assert sealer.open(sealed, HERE) == SECRET


def test_two_seals_of_one_secret_differ() -> None:
    sealer = Sealer({VERSION: KEY})
    assert sealer.seal(SECRET, HERE) != sealer.seal(SECRET, HERE)


def test_another_rows_binding_does_not_open_it() -> None:
    sealer = Sealer({VERSION: KEY})
    with pytest.raises(Unsealable):
        sealer.open(sealer.seal(SECRET, HERE), bound_to(11, "sure"))


def test_another_key_does_not_open_it() -> None:
    with pytest.raises(Unsealable):
        Sealer({VERSION: os.urandom(32)}).open(Sealer({VERSION: KEY}).seal(SECRET, HERE), HERE)


@pytest.mark.parametrize("at", [0, 5, 20, -1])
def test_an_altered_byte_does_not_open(at: int) -> None:
    sealer = Sealer({VERSION: KEY})
    sealed = bytearray(sealer.seal(SECRET, HERE))
    sealed[at] ^= 0x01
    with pytest.raises(Unsealable):
        sealer.open(bytes(sealed), HERE)


def test_a_rotated_key_opens_the_old_version_and_seals_the_new() -> None:
    old = Sealer({1: KEY}).seal(SECRET, HERE)
    rotated = Sealer({1: KEY, 2: os.urandom(32)}, current=2)
    assert rotated.open(old, HERE) == SECRET
    assert rotated.seal(SECRET, HERE)[0] == 2


def test_too_short_does_not_open() -> None:
    with pytest.raises(Unsealable):
        Sealer({VERSION: KEY}).open(bytes([VERSION]) + b"short", HERE)


def test_a_key_setting_is_base64_of_32_bytes() -> None:
    assert key_from(base64.b64encode(KEY).decode() + "\n") == KEY
    for bad in ("not base64!", base64.b64encode(os.urandom(16)).decode(), ""):
        with pytest.raises(ValueError):
            key_from(bad)


def test_a_current_version_needs_its_key() -> None:
    with pytest.raises(ValueError):
        Sealer({1: KEY}, current=2)
