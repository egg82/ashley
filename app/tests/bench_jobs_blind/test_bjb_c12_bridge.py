"""Contract 12 and spec section 3: the bridge's three file routes, confined to the session's `in/` and `out/`, with flat
code-checked names, hard size and count ceilings, and a log line that never names a file."""

from pathlib import Path

from typing import Any

import pytest
from bjb_bridge_support import Bridge, Pki, build_bridge, data_of, fetch, files_bridge, listing, put, session_dir, tree

BAD_NAMES = ["..", ".hidden", "a%2Fb", "..%2F..%2Fetc%2Fpasswd", "a%00b", "%2Fetc%2Fpasswd", ".env", ".a"]


@pytest.fixture
def bridge(tmp_path: Path, pki: Pki) -> Bridge:
    return build_bridge(tmp_path, pki)


def test_c12_upload_writes_to_in_and_answers_the_byte_count(bridge: Bridge) -> None:
    sid, where = session_dir(bridge)
    got = put(bridge, sid, "p5.py", b"print(1)\n")
    assert (got.status, got.body) == (200, {"bytes": 9})
    assert (where / "in" / "p5.py").read_bytes() == b"print(1)\n"


def test_c12_an_upload_of_the_same_name_replaces_it(bridge: Bridge) -> None:
    sid, where = session_dir(bridge)
    put(bridge, sid, "p5.py", b"one")
    assert put(bridge, sid, "p5.py", b"two!").status == 200
    assert (where / "in" / "p5.py").read_bytes() == b"two!"
    assert [p.name for p in (where / "in").iterdir()] == ["p5.py"]


@pytest.mark.parametrize("name", BAD_NAMES)
def test_c12_a_name_with_a_slash_dots_a_leading_dot_or_a_nul_is_bad_request_and_writes_nothing(
        bridge: Bridge, name: str) -> None:
    sid, _ = session_dir(bridge)
    before = tree(bridge.root.parent)
    got = put(bridge, sid, name, b"x")
    assert (got.status, got.body) == (400, {"error": "bad_request"})
    assert tree(bridge.root.parent) == before


@pytest.mark.parametrize("name", ["a" * 101, "a b", "a;b", "p5.py\n"])
def test_c12_a_name_outside_the_pattern_is_bad_request(bridge: Bridge, name: str) -> None:
    sid, _ = session_dir(bridge)
    assert put(bridge, sid, name, b"x").status == 400


def test_c12_a_name_of_exactly_one_hundred_characters_is_accepted(bridge: Bridge) -> None:
    sid, where = session_dir(bridge)
    name = "a" + "b" * 99
    assert put(bridge, sid, name, b"x").status == 200
    assert (where / "in" / name).exists()


def test_c12_a_download_name_is_checked_as_an_upload_name_is(bridge: Bridge) -> None:
    sid, where = session_dir(bridge)
    (where / ".env").write_text("SECRET-ENV-MARK")
    (where / "out").mkdir()
    for name in (".env", "..%2F.env", "..", "a%2Fb", "x%00y"):
        got = fetch(bridge, sid, name)
        assert (got.status, got.body) == (400, {"error": "bad_request"})


def test_c12_a_name_reaching_into_a_directory_inside_out_is_bad_request(bridge: Bridge) -> None:
    sid, where = session_dir(bridge)
    (where / "out" / "inner").mkdir(parents=True)
    (where / "out" / "inner" / "f.txt").write_text("NESTED-MARK")
    got = fetch(bridge, sid, "inner%2Ff.txt")
    assert (got.status, got.body) == (400, {"error": "bad_request"}) and "NESTED-MARK" not in repr(got)


def test_c12_a_symlinked_in_is_bad_path_and_nothing_lands_where_it_points(bridge: Bridge) -> None:
    sid, where = session_dir(bridge)
    (where / "in").symlink_to(bridge.outside)
    got = put(bridge, sid, "p5.py", b"x")
    assert got.body == {"error": "bad_path"}
    assert list(bridge.outside.iterdir()) == []


def test_c12_a_symlinked_out_is_bad_path_for_the_listing_and_for_a_download(bridge: Bridge) -> None:
    sid, where = session_dir(bridge)
    (bridge.outside / "result.txt").write_text("OUTSIDE-MARK")
    (where / "out").symlink_to(bridge.outside)
    assert listing(bridge, sid).body == {"error": "bad_path"}
    assert fetch(bridge, sid, "result.txt").body == {"error": "bad_path"}


def test_c12_the_listing_has_regular_files_directly_in_out_and_nothing_else(bridge: Bridge) -> None:
    sid, where = session_dir(bridge)
    out = where / "out"
    out.mkdir()
    (out / "RESULT.md").write_text("done")
    (out / "part.stl").write_bytes(b"abcd")
    (out / "sub").mkdir()
    (out / "sub" / "deep.txt").write_text("deep")
    (out / "link.txt").symlink_to(where / "secret.txt")
    (where / "secret.txt").write_text("SECRET-MARK")
    got = listing(bridge, sid)
    assert got.status == 200
    raw: Any = got.body["files"]
    entries: list[Any] = [*raw]
    names = sorted((str(f["name"]), int(f["bytes"])) for f in entries)
    assert names == [("RESULT.md", 4), ("part.stl", 4)]


def test_c12_a_download_answers_the_file_bytes(bridge: Bridge) -> None:
    sid, where = session_dir(bridge)
    (where / "out").mkdir()
    (where / "out" / "part.stl").write_bytes(b"\x00\x01solid")
    got = fetch(bridge, sid, "part.stl")
    assert got.status == 200 and data_of(got) == b"\x00\x01solid"


def test_c12_a_downloaded_symlink_never_gives_what_it_points_at(bridge: Bridge) -> None:
    sid, where = session_dir(bridge)
    (where / "out").mkdir()
    (where / "secret.txt").write_text("SECRET-MARK")
    (where / "out" / "link.txt").symlink_to(where / "secret.txt")
    got = fetch(bridge, sid, "link.txt")
    assert got.status >= 400 and "SECRET-MARK" not in repr(got)


def test_c12_a_download_never_reaches_the_rest_of_the_session_directory(bridge: Bridge) -> None:
    sid, where = session_dir(bridge)
    (where / "out").mkdir()
    (where / ".env").write_text("SECRET-ENV-MARK")
    (where / "notes.txt").write_text("SECRET-NOTES-MARK")
    for name in ("notes.txt", ".env"):
        got = fetch(bridge, sid, name)
        assert got.status >= 400 and "SECRET" not in repr(got)


def test_c12_a_body_over_max_file_bytes_is_413_and_nothing_is_written(bridge: Bridge) -> None:
    small = files_bridge(bridge, max_file_bytes=64)
    sid, _ = session_dir(small)
    before = tree(small.root.parent)
    got = put(small, sid, "big.bin", b"x" * 65)
    assert got.status == 413
    assert tree(small.root.parent) == before


def test_c12_a_body_of_exactly_max_file_bytes_is_accepted(bridge: Bridge) -> None:
    small = files_bridge(bridge, max_file_bytes=64)
    sid, _ = session_dir(small)
    assert put(small, sid, "ok.bin", b"x" * 64).status == 200


def test_c12_a_content_length_over_the_ceiling_is_413_before_the_body_is_read(bridge: Bridge) -> None:
    small = files_bridge(bridge, max_file_bytes=64)
    sid, where = session_dir(small)
    got = put(small, sid, "big.bin", b"x", length=10_000)
    assert got.status == 413
    assert not (where / "in" / "big.bin").exists()


def test_c12_past_max_files_an_upload_is_too_many(bridge: Bridge) -> None:
    small = files_bridge(bridge, max_files=2)
    sid, where = session_dir(small)
    assert put(small, sid, "a.txt", b"1").status == 200
    assert put(small, sid, "b.txt", b"2").status == 200
    got = put(small, sid, "c.txt", b"3")
    assert got.body == {"error": "too_many"}
    assert not (where / "in" / "c.txt").exists()


def test_c12_the_default_ceilings_are_the_specified_ones(bridge: Bridge) -> None:
    assert bridge.config.max_file_bytes == 26214400
    assert bridge.config.max_files == 32


def test_c12_a_session_outside_the_roots_is_dir_not_allowed_for_every_file_call(bridge: Bridge) -> None:
    made = bridge.add("alpha", cwd=str(bridge.outside))
    (bridge.outside / "out").mkdir()
    (bridge.outside / "out" / "x.txt").write_text("y")
    for got in (put(bridge, made.session_id, "p5.py", b"x"), listing(bridge, made.session_id),
                fetch(bridge, made.session_id, "x.txt")):
        assert got.body == {"error": "dir_not_allowed"}
    assert not (bridge.outside / "in").exists()


def test_c12_an_unknown_session_is_not_found(bridge: Bridge) -> None:
    ghost = "11111111-2222-4333-8444-555555555555"
    assert put(bridge, ghost, "p5.py", b"x").body == {"error": "not_found"}
    assert listing(bridge, ghost).body == {"error": "not_found"}


def test_c12_the_file_routes_keep_mtls_auth_and_the_person_lock(bridge: Bridge) -> None:
    sid, where = session_dir(bridge)
    assert put(bridge, sid, "p5.py", b"x", token="wrong").status == 401
    assert put(bridge, sid, "p5.py", b"x", token=None).status == 401
    assert put(bridge, sid, "p5.py", b"x", person="someone-else").status in (401, 403)
    assert not (where / "in").exists()


def test_c12_whoami_gains_the_files_capability_and_the_new_version(bridge: Bridge) -> None:
    got = bridge.get("/v1/whoami")
    assert got.body["capabilities"] == ["files"]
    assert got.body["bridge_version"] == "0.3.0"


def test_c19_the_files_log_line_names_the_call_and_never_a_file_name_or_its_bytes(bridge: Bridge) -> None:
    sid, _ = session_dir(bridge)
    put(bridge, sid, "NAMEMARK-81.txt", b"BYTESMARK-17")
    listing(bridge, sid)
    fetch(bridge, sid, "NAMEMARK-81.txt")
    text = bridge.log.text()
    for call in ("upload", "outputs", "download"):
        assert call in text
    assert "NAMEMARK" not in text and "BYTESMARK" not in text
