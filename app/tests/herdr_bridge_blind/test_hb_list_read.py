"""Listing sessions and reading a screen."""

import hashlib

import pytest
from herdr_bridge.jsonget import items
from herdr_bridge_blind_support import SID, Bridge


def sessions(b: Bridge) -> list[dict[str, object]]:
    r = b.get("/v1/sessions")
    assert r.status == 200
    return items(r.body["sessions"])


def test_a_session_is_listed_by_its_claude_session_id_with_label_dir_status_and_seq(bridge: Bridge) -> None:
    a = bridge.add("alpha", "working", cwd="/home/person/proj", seq=42)
    [one] = sessions(bridge)
    assert one["id"] == a.session_id
    assert one["label"] == "alpha"
    assert str(one["dir"]).endswith("proj")
    assert one["status"] == "working"
    assert one["seq"] == 42
    assert one["last_typed_at"] is None
    assert bridge.get("/v1/sessions").body["last_typed_at"] is None


@pytest.mark.parametrize("status", ["idle", "working", "blocked", "done", "unknown"])
def test_each_documented_status_is_reported_as_itself(bridge: Bridge, status: str) -> None:
    bridge.add("alpha", status)
    assert sessions(bridge)[0]["status"] == status


def test_a_status_herdr_invents_is_unknown(bridge: Bridge) -> None:
    bridge.add("alpha", "levitating")
    assert sessions(bridge)[0]["status"] == "unknown"


def test_only_claude_sessions_with_a_session_id_are_listed(bridge: Bridge) -> None:
    keep = bridge.add("keep")
    bridge.add("codex-one", agent="codex")
    bridge.add("nosession", with_session=False)
    assert [s["id"] for s in sessions(bridge)] == [keep.session_id]


def test_an_empty_herdr_lists_nothing(bridge: Bridge) -> None:
    assert sessions(bridge) == []


def test_listing_never_changes_anything(bridge: Bridge) -> None:
    bridge.add("alpha")
    sessions(bridge)
    assert bridge.herdr.changes() == []


@pytest.mark.parametrize("how", ["missing", "timeout"])
def test_herdr_not_running_or_not_answering_is_herdr_unavailable_for_reads(bridge: Bridge, how: str) -> None:
    bridge.herdr.fail[("agent", "list")] = how
    r = bridge.get("/v1/sessions")
    assert (r.status, r.body) == (503, {"error": "herdr_unavailable"})


def test_herdr_answering_an_error_is_herdr_unavailable(bridge: Bridge) -> None:
    bridge.herdr.fail[("agent", "list")] = "internal_error"
    r = bridge.get("/v1/sessions")
    assert (r.status, r.body) == (503, {"error": "herdr_unavailable"})


def test_read_returns_the_screen_text_and_revision(bridge: Bridge) -> None:
    a = bridge.add("alpha")
    r = bridge.get(f"/v1/sessions/{a.session_id}/read")
    assert r.status == 200
    assert "SCREEN-MARKER-7" in str(r.body["text"])
    assert r.body["revision"] == 11
    assert isinstance(r.body["truncated"], bool)


def wanted(argv: tuple[str, ...], n: int) -> bool:
    return str(n) in argv or any(a.endswith(f"={n}") for a in argv)


def test_read_asks_herdr_for_120_lines_by_default(bridge: Bridge) -> None:
    a = bridge.add("alpha")
    bridge.get(f"/v1/sessions/{a.session_id}/read")
    [cmd] = bridge.herdr.commands("agent", "read")
    assert wanted(cmd, 120)


@pytest.mark.parametrize("n", [1, 2, 399, 400])
def test_read_accepts_lines_from_1_to_400(bridge: Bridge, n: int) -> None:
    a = bridge.add("alpha")
    assert bridge.get(f"/v1/sessions/{a.session_id}/read", lines=str(n)).status == 200
    [cmd] = bridge.herdr.commands("agent", "read")
    assert wanted(cmd, n)


@pytest.mark.parametrize("n", ["0", "-1", "401", "1000", "abc", "", "1.5", "1e2", " 5", "0x10", "99999999999999999999"])
def test_read_refuses_lines_outside_1_to_400(bridge: Bridge, n: str) -> None:
    a = bridge.add("alpha")
    r = bridge.get(f"/v1/sessions/{a.session_id}/read", lines=n)
    assert (r.status, r.body) == (400, {"error": "bad_request"})
    assert bridge.herdr.commands("agent", "read") == []


def test_read_goes_to_the_pane_of_that_session_only(bridge: Bridge) -> None:
    a, b = bridge.add("alpha"), bridge.add("bravo")
    bridge.get(f"/v1/sessions/{b.session_id}/read")
    [cmd] = bridge.herdr.commands("agent", "read")
    assert any(w in (b.pane_id, b.name, b.session_id) for w in cmd)
    assert not any(w in (a.pane_id, a.name, a.session_id) for w in cmd)


@pytest.mark.parametrize(
    "sid",
    [SID, SID.upper(), "not-a-session", "../../etc/passwd", "w1:p1234", "alpha", "%2e%2e", SID + "x", SID[:-1]],
)
def test_read_of_an_unknown_session_is_not_found(bridge: Bridge, sid: str) -> None:
    bridge.add("alpha")
    r = bridge.get(f"/v1/sessions/{sid}/read")
    assert (r.status, r.body) == (404, {"error": "not_found"})
    assert bridge.herdr.commands("agent", "read") == []


def test_a_session_is_not_found_by_its_label_or_pane_id(bridge: Bridge) -> None:
    a = bridge.add("alpha")
    for ident in (a.name, a.pane_id, a.tab_id):
        assert bridge.get(f"/v1/sessions/{ident}/read").status == 404


def test_the_hash_prefix_helper_is_sha256_first_eight_digits() -> None:
    from herdr_bridge.logs import short

    assert short(SID) == hashlib.sha256(SID.encode()).hexdigest()[:8]


@pytest.mark.parametrize("n", ["١٢", "²", "４２", "5\n", "+5", "５"])
def test_read_lines_must_be_plain_ascii_digits(bridge: Bridge, n: str) -> None:
    a = bridge.add("alpha")
    r = bridge.get(f"/v1/sessions/{a.session_id}/read", lines=n)
    assert (r.status, r.body) == (400, {"error": "bad_request"})
    assert bridge.herdr.commands("agent", "read") == []
