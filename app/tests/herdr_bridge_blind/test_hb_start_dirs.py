"""Starting a session: only under the allow-listed roots."""

import os
from pathlib import Path

import pytest
from herdr_bridge.jsonget import items
from herdr_bridge_blind_pki import Pki
from herdr_bridge_blind_support import Bridge, build_bridge

REFUSED = (403, {"error": "dir_not_allowed"})


def refused(b: Bridge, directory: object) -> None:
    r = b.start(directory)
    assert (r.status, r.body) == REFUSED, directory
    assert b.herdr.changes() == []


def test_a_directory_under_the_root_starts_a_session_there(bridge: Bridge) -> None:
    d = bridge.mkdir("proj")
    r = bridge.start(d, "newone")
    assert r.status in (200, 201)
    assert r.body["label"] == "newone"
    assert r.body["status"] in ("idle", "working", "done")
    assert r.body["id"]
    [tab] = bridge.herdr.commands("tab", "create")
    assert str(d) in tab
    assert len(bridge.herdr.commands("agent", "start")) == 1


def test_a_deeper_directory_is_under_the_root(bridge: Bridge) -> None:
    d = bridge.mkdir("a", "b", "c")
    assert bridge.start(d).status in (200, 201)


def test_a_directory_with_a_trailing_slash_or_dot_segments_inside_the_root_is_allowed(bridge: Bridge) -> None:
    bridge.mkdir("proj")
    assert bridge.start(f"{bridge.root}/proj/").status in (200, 201)


def test_the_new_session_is_listed_and_reported_like_any_other(bridge: Bridge) -> None:
    r = bridge.start(bridge.mkdir("proj"), "listed")
    found = items(bridge.get("/v1/sessions").body["sessions"])
    assert [s["id"] for s in found] == [r.body["id"]]


@pytest.mark.parametrize("target", ["/", "/etc", "/tmp", "/root", "/proc/self"])
def test_an_absolute_path_outside_the_roots_is_refused(bridge: Bridge, target: str) -> None:
    refused(bridge, target)


def test_a_real_directory_beside_the_root_is_refused(bridge: Bridge) -> None:
    refused(bridge, bridge.outside)


def test_a_directory_whose_name_merely_begins_with_the_root_is_refused(bridge: Bridge) -> None:
    sibling = Path(str(bridge.root) + "-evil")
    sibling.mkdir()
    refused(bridge, sibling)
    refused(bridge, str(bridge.root) + "x")


def test_dot_dot_out_of_the_root_is_refused(bridge: Bridge) -> None:
    bridge.mkdir("sub")
    refused(bridge, f"{bridge.root}/sub/../../{bridge.outside.name}")
    refused(bridge, f"{bridge.root}/../{bridge.outside.name}")
    refused(bridge, f"{bridge.root}/..")
    refused(bridge, f"{bridge.root}/sub/../../..")


def test_dot_dot_that_stays_inside_the_root_is_judged_by_where_it_lands(bridge: Bridge) -> None:
    bridge.mkdir("sub")
    bridge.mkdir("other")
    assert bridge.start(f"{bridge.root}/sub/../other").status in (200, 201)


def test_a_symlink_inside_the_root_to_outside_is_refused(bridge: Bridge) -> None:
    link = bridge.root / "escape"
    link.symlink_to(bridge.outside)
    refused(bridge, link)
    refused(bridge, link / "deeper")


def test_a_symlink_to_a_directory_that_is_outside_through_two_hops_is_refused(bridge: Bridge) -> None:
    hop = bridge.outside / "hop"
    hop.symlink_to(bridge.root)
    (bridge.root / "back").symlink_to(bridge.outside)
    refused(bridge, bridge.root / "back" / "hop" / ".." / "..")


def test_a_symlink_inside_the_root_to_inside_is_allowed_and_started_at_the_real_path(bridge: Bridge) -> None:
    real = bridge.mkdir("real")
    (bridge.root / "alias").symlink_to(real)
    assert bridge.start(bridge.root / "alias").status in (200, 201)
    [tab] = bridge.herdr.commands("tab", "create")
    assert str(real) in tab


def test_a_directory_swapped_for_a_symlink_after_the_first_start_is_refused(bridge: Bridge) -> None:
    d = bridge.mkdir("proj")
    assert bridge.start(d, "first").status in (200, 201)
    d.rmdir()
    d.symlink_to(bridge.outside)
    bridge.herdr.calls.clear()
    refused(bridge, d)


def test_a_missing_directory_and_an_outside_directory_get_the_same_answer(bridge: Bridge) -> None:
    missing_outside = bridge.start("/nonexistent/place")
    exists_outside = bridge.start(bridge.outside)
    assert missing_outside.body == exists_outside.body == {"error": "dir_not_allowed"}
    assert missing_outside.status == exists_outside.status == 403


def test_a_file_is_not_a_directory(bridge: Bridge) -> None:
    f = bridge.root / "afile"
    f.write_text("x")
    refused(bridge, f)
    refused(bridge, f / "inside")


def test_a_relative_path_is_not_an_allowed_directory(bridge: Bridge) -> None:
    bridge.mkdir("proj")
    for rel in ("proj", "./proj", "../work/proj", "."):
        r = bridge.start(rel)
        assert r.status == 403 and r.body == {"error": "dir_not_allowed"}, rel
    assert bridge.herdr.changes() == []


def test_a_relative_path_resolved_against_the_bridge_cwd_does_not_pass(bridge: Bridge, monkeypatch: pytest.MonkeyPatch) -> None:
    bridge.mkdir("proj")
    monkeypatch.chdir(bridge.root)
    r = bridge.start("proj")
    assert r.status == 403 and bridge.herdr.changes() == []


def test_a_home_shorthand_is_not_expanded(bridge: Bridge, monkeypatch: pytest.MonkeyPatch) -> None:
    bridge.mkdir("proj")
    monkeypatch.setenv("HOME", str(bridge.root))
    r = bridge.start("~/proj")
    assert r.status == 403 and bridge.herdr.changes() == []


@pytest.mark.parametrize("bad", ["", " ", "a" * 5000, "\n", "$HOME", "${HOME}/x"])
def test_odd_strings_never_pass_and_never_crash(bridge: Bridge, bad: str) -> None:
    r = bridge.start(bad)
    assert 400 <= r.status < 500
    assert bridge.herdr.changes() == []


@pytest.mark.parametrize("tail", ["", "/etc", "/../../.."])
def test_a_nul_byte_in_dir_is_refused_not_raised(bridge: Bridge, tail: str) -> None:
    d = bridge.mkdir("proj")
    r = bridge.start(f"{d}\x00{tail}")
    assert 400 <= r.status < 500
    assert bridge.herdr.changes() == []


@pytest.mark.parametrize("value", [None, 5, ["/x"], {"a": 1}, True])
def test_a_dir_that_is_not_a_string_is_refused(bridge: Bridge, value: object) -> None:
    r = bridge.post("/v1/sessions", {"dir": value, "label": "abc"})
    assert 400 <= r.status < 500
    assert bridge.herdr.changes() == []


def test_a_request_with_no_dir_is_refused(bridge: Bridge) -> None:
    r = bridge.post("/v1/sessions", {"label": "abc"})
    assert 400 <= r.status < 500
    assert bridge.herdr.changes() == []


def test_a_second_root_is_allowed_and_nothing_between_the_roots_is(tmp_path: Path, pki: Pki) -> None:
    second = tmp_path / "second"
    second.mkdir()
    (tmp_path / "b").mkdir()
    b = build_bridge(tmp_path / "b", pki, extra_roots=(second,))
    assert b.start(second).status in (200, 201)
    assert b.start(tmp_path).status == 403
    assert b.start(tmp_path / "b").status == 403


def test_the_root_itself_never_lets_a_parent_through(bridge: Bridge) -> None:
    parent = bridge.root.parent
    refused(bridge, parent)
    assert os.path.realpath(parent) == str(parent)
