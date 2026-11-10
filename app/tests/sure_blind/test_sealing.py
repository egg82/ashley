"""Sealing a secret (`connections.sealing`): it opens only for the household and kind it was sealed for, under the key
it was sealed with, and unaltered; the sealed form never holds the secret."""

import base64
import os

import pytest
from ashley.connections.sealing import Sealer, Unsealable, bound_to, key_from

KEY = os.urandom(32)
SECRET = "sk-test-0123456789-the-secret"  # gitleaks:allow (test fixture)


def sealer(key: bytes = KEY) -> Sealer:
    return Sealer({1: key}, current=1)


def test_a_sealed_secret_opens_for_its_binding() -> None:
    bound = bound_to(7, "sure")
    assert sealer().open(sealer().seal(SECRET, bound), bound) == SECRET


@pytest.mark.parametrize("secret", ["", "k", "ключ-🔑-鍵", "a" * 5000])
def test_any_secret_round_trips(secret: str) -> None:
    bound = bound_to(1, "sure")
    assert sealer().open(sealer().seal(secret, bound), bound) == secret


def test_the_sealed_form_does_not_hold_the_secret() -> None:
    sealed = sealer().seal(SECRET, bound_to(7, "sure"))
    assert isinstance(sealed, bytes) and SECRET.encode() not in sealed
    assert base64.b64encode(SECRET.encode()) not in sealed


def test_sealing_twice_gives_different_bytes() -> None:
    bound = bound_to(7, "sure")
    assert sealer().seal(SECRET, bound) != sealer().seal(SECRET, bound)


def test_a_value_moved_to_another_household_does_not_open() -> None:
    sealed = sealer().seal(SECRET, bound_to(7, "sure"))
    with pytest.raises(Unsealable):
        sealer().open(sealed, bound_to(8, "sure"))


def test_a_value_moved_to_another_kind_does_not_open() -> None:
    sealed = sealer().seal(SECRET, bound_to(7, "sure"))
    with pytest.raises(Unsealable):
        sealer().open(sealed, bound_to(7, "other"))


def test_bindings_differ_by_household_and_by_kind_and_are_stable() -> None:
    assert bound_to(7, "sure") == bound_to(7, "sure")
    assert len({bound_to(7, "sure"), bound_to(8, "sure"), bound_to(7, "other"), bound_to(78, "sure")}) == 4


def test_another_key_does_not_open() -> None:
    sealed = sealer().seal(SECRET, bound_to(7, "sure"))
    with pytest.raises(Unsealable):
        sealer(os.urandom(32)).open(sealed, bound_to(7, "sure"))


def test_every_altered_byte_is_refused() -> None:
    bound = bound_to(7, "sure")
    sealed = sealer().seal(SECRET, bound)
    for i in range(len(sealed)):
        altered = sealed[:i] + bytes([sealed[i] ^ 1]) + sealed[i + 1:]
        with pytest.raises(Unsealable):
            sealer().open(altered, bound)


@pytest.mark.parametrize("cut", [0, 1, 5, 13, 20])
def test_a_truncated_value_is_unsealable_not_another_error(cut: int) -> None:
    bound = bound_to(7, "sure")
    with pytest.raises(Unsealable):
        sealer().open(sealer().seal(SECRET, bound)[:cut], bound)


def test_a_value_sealed_under_an_older_key_opens_while_that_key_is_held() -> None:
    old, new = os.urandom(32), os.urandom(32)
    bound = bound_to(7, "sure")
    sealed = Sealer({1: old}, current=1).seal(SECRET, bound)
    rotated = Sealer({1: old, 2: new}, current=2)
    assert rotated.open(sealed, bound) == SECRET
    fresh = rotated.seal(SECRET, bound)
    assert fresh[0] == 2 and sealed[0] == 1
    with pytest.raises(Unsealable):
        Sealer({2: new}, current=2).open(sealed, bound)


def test_the_first_byte_names_the_key_version() -> None:
    assert Sealer({5: KEY}, current=5).seal(SECRET, bound_to(1, "sure"))[0] == 5


def test_key_from_refuses_text_with_stray_characters_inside() -> None:
    text = base64.b64encode(KEY).decode()
    for stray in ("!", "$", " ", "-"):
        with pytest.raises(ValueError):
            key_from(text[:10] + stray + text[10:])


def test_key_from_reads_32_bytes_of_base64() -> None:
    assert key_from(base64.b64encode(KEY).decode()) == KEY


@pytest.mark.parametrize("text", ["", "not base64 !!", base64.b64encode(b"short").decode(),
                                  base64.b64encode(bytes(33)).decode(), base64.b64encode(bytes(16)).decode()])
def test_key_from_refuses_anything_else(text: str) -> None:
    with pytest.raises(ValueError):
        key_from(text)
