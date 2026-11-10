"""`take` judges a file and keeps it under `bench/<household>/<sha256>`: content-addressed per household, refused before
anything is stored, the limit from config, and names reduced to a plain file name."""

import dataclasses
import logging

import pytest
from ashley import services
from ashley.files.intake import NAME_CHARS, Refused, key_of, name_of, take
from ashley.files.store import NullStore, ObjectStore, StoreUnavailable
from files_blind_support import fields_of, go as run, log_text, CONFIG, HTML, PDF, PNG, TEXT, FakeStore, sha
from hypothesis import given, settings
from hypothesis import strategies as st


@pytest.fixture
def store():
    s = FakeStore()
    services.register(ObjectStore, s)
    yield s
    services.unregister(ObjectStore)


def taking(household: int, data: bytes, name: str = "f.bin", declared: str = ""):
    return run(take(household, data, name, declared, CONFIG))


def test_the_key_is_bench_household_and_hash() -> None:
    assert key_of(7, "ab" * 32) == "bench/7/" + "ab" * 32


def test_a_taken_file_is_described_and_kept_whole_under_its_key(store: FakeStore) -> None:
    got = taking(3, PNG, "pic.png", "image/png")
    assert (got.sha256, got.size, got.media_type, got.name) == (sha(PNG), len(PNG), "image/png", "pic.png")
    assert store.held == {f"bench/3/{sha(PNG)}": PNG}


def test_the_stored_type_is_the_sniffed_one_not_the_declared(store: FakeStore) -> None:
    assert taking(1, HTML, "page.html", "text/html").media_type == "text/plain"
    assert taking(1, PDF, "x", "application/octet-stream").media_type == "application/pdf"


def test_the_same_bytes_in_one_household_are_one_object_and_in_two_are_two(store: FakeStore) -> None:
    a, b, c = taking(1, TEXT, "a.txt"), taking(1, TEXT, "b.txt"), taking(2, TEXT, "a.txt")
    assert a.sha256 == b.sha256 == c.sha256
    assert set(store.held) == {key_of(1, a.sha256), key_of(2, a.sha256)}
    assert {k.split("/")[1] for k in store.held} == {"1", "2"}


def test_different_bytes_are_different_objects(store: FakeStore) -> None:
    taking(1, b"one")
    taking(1, b"two")
    assert len(store.held) == 2


@pytest.mark.parametrize(("data", "reason"), [(b"", "empty"), (b"\x00\x01\x02", "type_not_allowed")])
def test_a_refused_file_stores_nothing(store: FakeStore, data: bytes, reason: str) -> None:
    with pytest.raises(Refused) as e:
        taking(1, data)
    assert e.value.reason == reason
    assert store.held == {} and store.calls.of("put") == []


def test_a_declared_known_type_the_bytes_are_not_is_refused_as_a_mismatch(store: FakeStore) -> None:
    with pytest.raises(Refused) as e:
        taking(1, PNG, "x.pdf", "application/pdf")
    assert e.value.reason == "type_mismatch" and store.held == {}


def test_the_limit_comes_from_the_config_and_the_largest_file_is_taken(store: FakeStore) -> None:
    small = dataclasses.replace(CONFIG, max_bytes=10)
    assert run(take(1, b"a" * 10, "a", "", small)).size == 10
    with pytest.raises(Refused) as e:
        run(take(1, b"a" * 11, "a", "", small))
    assert e.value.reason == "too_large" and set(store.held) == {key_of(1, sha(b"a" * 10))}


def test_a_larger_limit_takes_what_the_default_would_not(store: FakeStore) -> None:
    big = dataclasses.replace(CONFIG, max_bytes=CONFIG.max_bytes * 2)
    data = b"a" * 64
    assert run(take(1, data, "a", "", dataclasses.replace(big, max_bytes=64))).size == 64
    with pytest.raises(Refused):
        run(take(1, data, "a", "", dataclasses.replace(big, max_bytes=63)))


def test_a_size_too_large_wins_over_nothing_stored_even_for_unreadable_bytes(store: FakeStore) -> None:
    with pytest.raises(Refused) as e:
        run(take(1, b"\x00" * 20, "a", "", dataclasses.replace(CONFIG, max_bytes=5)))
    assert e.value.reason == "too_large" and store.held == {}


def test_an_unreachable_store_raises_unavailable_and_an_unwired_one_too(store: FakeStore) -> None:
    store.down = True
    with pytest.raises(StoreUnavailable):
        taking(1, TEXT)
    services.register(ObjectStore, NullStore())
    with pytest.raises(StoreUnavailable):
        taking(1, TEXT)


def test_the_copies_a_taken_file_has_are_logged_without_its_name_or_bytes(store: FakeStore, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG):
        taking(5, b"the secret body text", "secret-name.txt")
    text = log_text(caplog)
    assert "secret-name" not in text and "secret body" not in text
    (stored,) = fields_of(caplog, "files.stored")
    assert (stored["household"], stored["size"], stored["media_type"], stored["copies"]) == (5, 20, "text/plain", 1)


@pytest.mark.parametrize(("raw", "plain"), [
    ("a%20b.txt", "a b.txt"), ("caf%C3%A9.csv", "café.csv"), ("plain.txt", "plain.txt"),
    ("dir/sub/x.png", "x.png"), ("..%2F..%2Fetc%2Fpasswd", "passwd"), ("C:\\dir\\x.txt", "x.txt"),
    ("a/b\\c.txt", "c.txt"), ("a%00b", "ab"), ("a\x07b\x1fc\x7f.txt", "abc.txt"), ("  x.txt  ", "x.txt"),
    ("", "file"), ("   ", "file"), ("%00%01", "file"), ("/", "file"), ("\x00", "file")])
def test_a_name_is_a_plain_file_name(raw: str, plain: str) -> None:
    assert name_of(raw) == plain


def test_a_name_is_cut_to_the_limit() -> None:
    assert name_of("x" * 500) == "x" * NAME_CHARS
    assert len(name_of("é" * 500)) == NAME_CHARS
    assert name_of("x" * NAME_CHARS) == "x" * NAME_CHARS


def test_a_taken_files_name_is_the_plain_name(store: FakeStore) -> None:
    assert taking(1, TEXT, "..%2F..%2Fsecret%2Fnotes.txt").name == "notes.txt"


@settings(max_examples=40)
@given(raw=st.text(max_size=400))
def test_property_a_name_never_holds_a_slash_or_control_character_and_fits(raw: str) -> None:
    n = name_of(raw)
    assert n and len(n) <= NAME_CHARS
    assert "/" not in n and "\\" not in n and all(ord(c) >= 32 and ord(c) != 127 for c in n)


@settings(max_examples=25)
@given(text=st.text(alphabet=st.characters(whitelist_categories=("L", "N")), min_size=1, max_size=30),
       h1=st.integers(1, 50), h2=st.integers(1, 50))
def test_property_keys_are_content_addressed_and_households_differ_by_prefix(text: str, h1: int, h2: int) -> None:
    s = FakeStore()
    services.register(ObjectStore, s)
    try:
        data = text.encode()
        a, b = taking(h1, data), taking(h2, data)
    finally:
        services.unregister(ObjectStore)
    assert a.sha256 == b.sha256 == sha(data)
    assert set(s.held) == {f"bench/{h1}/{sha(data)}", f"bench/{h2}/{sha(data)}"}
    assert (len(s.held) == 1) == (h1 == h2)


def test_a_name_cut_inside_a_word_gap_is_trimmed_after_the_cut() -> None:
    assert name_of("x" * (NAME_CHARS - 1) + " yyy") == "x" * (NAME_CHARS - 1)
