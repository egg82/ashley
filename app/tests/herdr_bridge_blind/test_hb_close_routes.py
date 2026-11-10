"""Closing a session, and the routes that must not exist."""

import pytest
from herdr_bridge_blind_support import ROUTES, SID, Bridge


@pytest.mark.parametrize("status", ["idle", "working", "done", "blocked", "unknown"])
def test_close_ends_that_sessions_pane(bridge: Bridge, status: str) -> None:
    a, other = bridge.add("alpha", status), bridge.add("bravo")
    r = bridge.post(f"/v1/sessions/{a.session_id}/close")
    assert (r.status, r.body) == (200, {"closed": True})
    [cmd] = bridge.herdr.changes()
    assert any(w in (a.pane_id, a.tab_id) for w in cmd)
    assert not any(w in (other.pane_id, other.tab_id, other.name) for w in cmd)
    assert [x.session_id for x in bridge.herdr.agents] == [other.session_id]


def test_close_of_an_unknown_session_is_not_found_and_closes_nothing(bridge: Bridge) -> None:
    keep = bridge.add("alpha")
    r = bridge.post(f"/v1/sessions/{SID}/close")
    assert (r.status, r.body) == (404, {"error": "not_found"})
    assert bridge.herdr.changes() == []
    assert len(bridge.herdr.agents) == 1 and bridge.herdr.agents[0] is keep


def test_close_twice_is_not_found_the_second_time(bridge: Bridge) -> None:
    a = bridge.add("alpha")
    assert bridge.post(f"/v1/sessions/{a.session_id}/close").status == 200
    assert bridge.post(f"/v1/sessions/{a.session_id}/close").status == 404
    assert len(bridge.herdr.changes()) == 1


@pytest.mark.parametrize("ident", ["alpha", "w1:pabc", "../..", "*", "all", "%00"])
def test_close_by_anything_but_a_session_id_is_not_found(bridge: Bridge, ident: str) -> None:
    a = bridge.add("alpha")
    for known in (a.name, a.pane_id, a.tab_id, ident):
        assert bridge.post(f"/v1/sessions/{known}/close").status == 404
    assert bridge.herdr.changes() == []


def test_a_close_that_times_out_is_unconfirmed(bridge: Bridge) -> None:
    a = bridge.add("alpha")
    bridge.herdr.fail[("pane", "close")] = "timeout"
    r = bridge.post(f"/v1/sessions/{a.session_id}/close")
    assert (r.status, r.body) == (504, {"error": "unconfirmed"})


def test_a_close_while_herdr_is_missing_is_herdr_unavailable(bridge: Bridge) -> None:
    a = bridge.add("alpha")
    bridge.herdr.fail[("agent", "list")] = "missing"
    r = bridge.post(f"/v1/sessions/{a.session_id}/close")
    assert (r.status, r.body) == (503, {"error": "herdr_unavailable"})


WRONG_METHOD = [
    ("POST", "/v1/whoami"),
    ("PUT", "/v1/whoami"),
    ("POST", "/v1/sessions/{sid}/read"),
    ("GET", "/v1/sessions/{sid}/prompt"),
    ("GET", "/v1/sessions/{sid}/close"),
    ("PUT", "/v1/sessions/{sid}/close"),
    ("DELETE", "/v1/sessions/{sid}"),
    ("DELETE", "/v1/sessions/{sid}/close"),
    ("GET", "/v1/sessions/{sid}"),
    ("PUT", "/v1/sessions"),
    ("DELETE", "/v1/sessions"),
    ("PATCH", "/v1/sessions/{sid}/prompt"),
    ("HEAD", "/v1/sessions/{sid}/close"),
    ("OPTIONS", "/v1/sessions/{sid}/close"),
]


@pytest.mark.parametrize("method,path", WRONG_METHOD)
def test_a_documented_path_with_the_wrong_method_does_nothing(bridge: Bridge, method: str, path: str) -> None:
    a = bridge.add("alpha")
    body = {"dir": str(bridge.mkdir("p")), "label": "abc"} if path.endswith("/v1/sessions") else {"text": "hi"}
    r = bridge.call(method, path.format(sid=a.session_id), body)
    assert 400 <= r.status < 500
    assert bridge.herdr.changes() == []
    assert len(bridge.herdr.agents) == 1


UNDOCUMENTED = [
    "/",
    "/v1",
    "/v2/whoami",
    "/v1/sessions/",
    "/v1/sessions/{sid}/keys",
    "/v1/sessions/{sid}/send",
    "/v1/sessions/{sid}/send-keys",
    "/v1/sessions/{sid}/input",
    "/v1/sessions/{sid}/exec",
    "/v1/sessions/{sid}/run",
    "/v1/sessions/{sid}/read/extra",
    "/v1/sessions/{sid}/close/extra",
    "/v1/sessions/{sid}/../close",
    "/v1/sessions/{sid}/prompt/",
    "/v1/panes",
    "/v1/exec",
    "/v1/herdr",
    "/v1/tabs",
    "/metrics",
    "/v1/sessions/%2e%2e/{sid}/close",
]


@pytest.mark.parametrize("path", UNDOCUMENTED)
@pytest.mark.parametrize("method", ["GET", "POST"])
def test_an_undocumented_route_is_not_found_and_does_nothing(bridge: Bridge, method: str, path: str) -> None:
    a = bridge.add("alpha")
    r = bridge.call(method, path.format(sid=a.session_id), {"text": "hi", "keys": "x", "cmd": "id"})
    assert (r.status, r.body) == (404, {"error": "not_found"})
    assert bridge.herdr.changes() == []


def test_the_documented_routes_are_exactly_six(bridge: Bridge) -> None:
    a = bridge.add("alpha")
    seen = [(m, p) for m, p, _ in ROUTES]
    assert len(set(seen)) == 6
    assert all(bridge.call(m, p.replace("11111111-2222-4333-8444-555555555555", a.session_id), b).status < 500
               for m, p, b in ROUTES)


def test_an_unhandled_failure_inside_herdr_handling_never_leaks_text(bridge: Bridge) -> None:
    bridge.herdr.fail[("agent", "list")] = "/home/secret/path exploded"
    r = bridge.get("/v1/sessions")
    assert set(r.body) == {"error"}
    assert "secret" not in str(r.body)


def test_close_passes_herdr_the_pane_and_no_options(bridge: Bridge) -> None:
    a = bridge.add("alpha")
    bridge.post(f"/v1/sessions/{a.session_id}/close")
    [cmd] = bridge.herdr.commands("pane", "close")
    assert not any(w.startswith("-") for w in cmd)
