"""The bridge's HTTP surface over a fake `herdr` that replays answers captured from the real CLI."""

import json
from collections.abc import Mapping
from pathlib import Path

import pytest
from herdr_bridge.api import MAX_BODY, MAX_PROMPT
from herdr_bridge.jsonget import items
from herdr_bridge.runner import HerdrMissing, HerdrTimeout, Outcome

from herdr_bridge_support import PERSON, THROWAWAY, Bridge, FakeHerdr, listing, ok, session_ids

LIST = ("agent", "list")
TABS = ("tab", "list")


def bridge(tmp_path: Path, extra: Mapping[tuple[str, ...], Outcome | Exception] | None = None) -> Bridge:
    replies: dict[tuple[str, ...], Outcome | Exception] = {
        LIST: listing(), TABS: ok("tab_list.json"), ("--version",): ok("version.out"),
    }
    replies.update(extra or {})
    tmp_path.mkdir(exist_ok=True)
    return Bridge(tmp_path, FakeHerdr(replies))


def test_list_carries_the_roots_a_start_may_name_as_real_absolute_paths(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    (tmp_path / "link").symlink_to(real)
    state = tmp_path / "state"
    state.mkdir()
    b = Bridge(state, FakeHerdr({LIST: listing(), TABS: ok("tab_list.json")}), (str(tmp_path / "link"), "/tmp"))
    assert b.get("/v1/sessions").body["roots"] == [str(real), str(Path("/tmp").resolve())]


def test_list_answers_claude_sessions_with_labels_dirs_and_statuses(tmp_path: Path) -> None:
    res = bridge(tmp_path).get("/v1/sessions")
    assert res.status == 200
    assert res.body["last_typed_at"] is None
    sessions = items(res.body["sessions"])
    assert [s["label"] for s in sessions] == ["app-2", "bridge-capture", "notes", "1", "1"]
    assert [s["status"] for s in sessions] == ["working", "done", "idle", "idle", "idle"]
    assert [s["id"] for s in sessions] == session_ids()
    capture = sessions[1]
    assert capture["dir"] == "bridge-capture-dir"
    assert capture["last_typed_at"] is None
    assert capture["seq"] == 1631


def test_list_asks_herdr_only_to_list(tmp_path: Path) -> None:
    b = bridge(tmp_path)
    b.get("/v1/sessions")
    assert b.runner.calls == [LIST, TABS]


def test_a_token_that_is_wrong_or_missing_is_refused_before_anything_runs(tmp_path: Path) -> None:
    b = bridge(tmp_path)
    for header in ("Bearer nope", "", "Basic dDBrZW4tZm9yLXRlc3Rz", "Bearer"):
        res = b.get("/v1/sessions", authorization=header)
        assert (res.status, res.body) == (401, {"error": "bad_token"})
    assert b.runner.calls == []
    assert b.person_on_disk() is None, "a refused token must not claim the bridge for a person"


def test_the_first_person_owns_the_bridge_and_everyone_else_is_refused(tmp_path: Path) -> None:
    b = bridge(tmp_path)
    assert b.get("/v1/whoami").body["person"] == PERSON
    assert b.person_on_disk() == PERSON
    res = b.get("/v1/sessions", x_ashley_person="8")
    assert (res.status, res.body) == (403, {"error": "wrong_person"})
    assert b.get("/v1/whoami", x_ashley_person="8").status == 403
    assert b.get("/v1/sessions").status == 200


def test_a_call_without_a_person_is_refused_and_records_nobody(tmp_path: Path) -> None:
    b = bridge(tmp_path)
    for value in ("", "a b", "x" * 65):
        assert b.get("/v1/whoami", x_ashley_person=value).body == {"error": "wrong_person"}
    assert b.person_on_disk() is None


def test_whoami_reports_the_versions(tmp_path: Path) -> None:
    body = bridge(tmp_path).get("/v1/whoami").body
    assert body == {"bridge_version": "0.4.0", "herdr_version": "0.9.5", "person": PERSON, "capabilities": ["files"]}


def test_whoami_with_herdr_gone_says_unknown_rather_than_failing(tmp_path: Path) -> None:
    b = bridge(tmp_path, {("--version",): HerdrMissing("herdr")})
    assert b.get("/v1/whoami").body["herdr_version"] is None


def test_unknown_routes_and_wrong_methods_are_not_found(tmp_path: Path) -> None:
    b = bridge(tmp_path)
    sid = THROWAWAY
    for res in (
        b.get("/v1/nothing"),
        b.get(f"/v1/sessions/{sid}/prompt"),
        b.post(f"/v1/sessions/{sid}/read", {}),
        b.get(f"/v1/sessions/{sid}/send-keys"),
        b.get("/v1/sessions/not-a-session-id/read"),
        b.get(f"/v1/sessions/{sid}"),
    ):
        assert (res.status, res.body) == (404, {"error": "not_found"})
    assert b.runner.calls == []


def test_read_returns_the_text_with_the_revision(tmp_path: Path) -> None:
    read = ("agent", "read", "w5H:pK", "--source", "recent-unwrapped", "--lines", "120")
    b = bridge(tmp_path, {read: ok("agent_read.txt")})
    res = b.get(f"/v1/sessions/{THROWAWAY}/read")
    assert res.status == 200
    assert res.body["text"] == (Path(__file__).parent / "herdr_captured" / "agent_read.txt").read_text()
    assert res.body["revision"] == 4
    assert res.body["truncated"] is False


def test_read_marks_a_full_window_truncated_and_honours_lines(tmp_path: Path) -> None:
    read = ("agent", "read", "w5H:pK", "--source", "recent-unwrapped", "--lines", "3")
    b = bridge(tmp_path, {read: Outcome(0, "a\nb\nc\n", "")})
    res = b.get(f"/v1/sessions/{THROWAWAY}/read", {"lines": "3"})
    assert res.body["truncated"] is True


@pytest.mark.parametrize("lines", ["0", "401", "-1", "x", "1.5", "", "٣"])
def test_read_refuses_lines_outside_1_to_400(tmp_path: Path, lines: str) -> None:
    b = bridge(tmp_path)
    assert b.get(f"/v1/sessions/{THROWAWAY}/read", {"lines": lines}).body == {"error": "bad_request"}
    assert b.runner.calls == []


def test_a_session_herdr_does_not_know_is_not_found(tmp_path: Path) -> None:
    res = bridge(tmp_path).get("/v1/sessions/00000000-0000-0000-0000-000000000000/read")
    assert (res.status, res.body) == (404, {"error": "not_found"})


def test_herdr_missing_or_failing_is_herdr_unavailable(tmp_path: Path) -> None:
    assert bridge(tmp_path, {LIST: HerdrMissing("herdr")}).get("/v1/sessions").body == {"error": "herdr_unavailable"}
    assert bridge(tmp_path / "b", {LIST: HerdrTimeout("agent")}).get("/v1/sessions").status == 503


def test_a_nul_byte_in_prompt_text_is_a_bad_request_and_reaches_no_command(tmp_path: Path) -> None:
    b = bridge(tmp_path)
    res = b.post(f"/v1/sessions/{THROWAWAY}/prompt", {"text": "hi\x00there"})
    assert (res.status, res.body) == (400, {"error": "bad_request"})
    assert b.runner.calls == []


def test_the_body_limit_holds_the_largest_text_in_standard_escaped_json_and_no_more() -> None:
    worst = json.dumps({"text": "\U0001f600" * MAX_PROMPT})
    assert len(worst) <= MAX_BODY < 2 * len(worst)
