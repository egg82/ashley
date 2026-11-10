"""The calls that change something: prompt, start and close, and what the call log may say about them."""

import json
from collections.abc import Mapping
from pathlib import Path

import pytest
from herdr_bridge.runner import HerdrMissing, HerdrTimeout, Outcome

from herdr_bridge_support import THROWAWAY, Bridge, FakeHerdr, digest8, failed, listing, ok

LIST = ("agent", "list")
TABS = ("tab", "list")
PANE = "w5H:pK"
DONE = THROWAWAY
PROMPT = ("agent", "prompt", PANE, "reply with ok")
Replies = Mapping[tuple[str, ...], Outcome | Exception | list[Outcome]]


def made(tmp_path: Path, extra: Replies | None = None, statuses: Mapping[str, str] | None = None,
         drop: tuple[str, ...] = (), roots: tuple[str, ...] = ("/tmp",), state: str = "state") -> Bridge:
    before_and_after = [listing(statuses, drop), listing(statuses)]  # a dropped session appears once it is started
    replies: dict[tuple[str, ...], Outcome | Exception | list[Outcome]] = {
        LIST: before_and_after if drop else listing(statuses), TABS: ok("tab_list.json")}
    replies.update(extra or {})
    (tmp_path / state).mkdir()
    return Bridge(tmp_path / state, FakeHerdr(replies), roots)


def prompt(b: Bridge, session: str = DONE, text: str = "reply with ok") -> tuple[int, dict[str, object]]:
    res = b.post(f"/v1/sessions/{session}/prompt", {"text": text})
    return res.status, res.body


def test_prompt_submits_to_the_pane_of_an_idle_or_done_session(tmp_path: Path) -> None:
    b = made(tmp_path, {PROMPT: ok("agent_prompt.json")})
    assert prompt(b) == (200, {"submitted": True})
    assert b.runner.calls[-1] == PROMPT


def test_prompt_is_refused_unless_the_session_is_ready(tmp_path: Path) -> None:
    for status, code in (("working", "busy"), ("blocked", "blocked"), ("unknown", "unknown_state")):
        b = made(tmp_path, statuses={DONE: status}, state=status)
        assert prompt(b) == (409, {"error": code})
        assert PROMPT not in b.runner.calls


def test_prompt_refuses_a_blocked_answer_herdr_gives_after_the_check(tmp_path: Path) -> None:
    blocked = Outcome(1, "", '{"error":{"code":"agent_blocked","message":"x"},"id":"cli:agent:prompt"}')
    assert prompt(made(tmp_path, {PROMPT: blocked})) == (409, {"error": "blocked"})


def test_a_prompt_that_timed_out_is_unconfirmed(tmp_path: Path) -> None:
    assert prompt(made(tmp_path, {PROMPT: HerdrTimeout("agent")})) == (504, {"error": "unconfirmed"})


def test_a_prompt_herdr_could_not_start_is_herdr_unavailable(tmp_path: Path) -> None:
    assert prompt(made(tmp_path, {PROMPT: HerdrMissing("herdr")})) == (503, {"error": "herdr_unavailable"})


@pytest.mark.parametrize("body", [b"", b"[]", b"{}", b'{"text": ""}', b'{"text": "  "}', b'{"text": 1}',
                                  b'{"text": "a", "extra": 1}', b'{"text": "' + b"a" * 8001 + b'"}', b"\xff"])
def test_prompt_refuses_a_bad_body_before_asking_herdr(tmp_path: Path, body: bytes) -> None:
    b = made(tmp_path)
    assert b.post(f"/v1/sessions/{DONE}/prompt", body).body == {"error": "bad_request"}
    assert b.runner.calls == []


def test_prompt_accepts_the_longest_allowed_text(tmp_path: Path) -> None:
    text = "a" * 8000
    b = made(tmp_path, {("agent", "prompt", PANE, text): ok("agent_prompt.json")})
    assert prompt(b, text=text)[0] == 200


def test_close_closes_the_sessions_pane_and_nothing_else(tmp_path: Path) -> None:
    close = ("pane", "close", PANE)
    b = made(tmp_path, {close: ok("pane_close.json")})
    res = b.post(f"/v1/sessions/{DONE}/close", {})
    assert (res.status, res.body) == (200, {"closed": True})
    assert b.runner.calls[-1] == close


def test_close_of_an_unknown_session_closes_nothing(tmp_path: Path) -> None:
    b = made(tmp_path)
    res = b.post("/v1/sessions/00000000-0000-0000-0000-000000000000/close", {})
    assert (res.status, res.body) == (404, {"error": "not_found"})
    assert not any(c[:2] == ("pane", "close") for c in b.runner.calls)


def test_close_that_timed_out_is_unconfirmed(tmp_path: Path) -> None:
    b = made(tmp_path, {("pane", "close", PANE): HerdrTimeout("pane")})
    assert b.post(f"/v1/sessions/{DONE}/close", {}).body == {"error": "unconfirmed"}


def test_the_bridge_only_ever_sends_the_commands_it_is_for(tmp_path: Path) -> None:
    """Every call a full tour makes, checked against the commands that exist; nothing sends keys, text or input."""
    proj = tmp_path / "proj"
    proj.mkdir()
    b = made(tmp_path, {
        PROMPT: ok("agent_prompt.json"), ("pane", "close", PANE): ok("pane_close.json"),
        ("agent", "read", PANE, "--source", "recent-unwrapped", "--lines", "120"): ok("agent_read.txt"),
    })
    b.get("/v1/sessions")
    b.get(f"/v1/sessions/{DONE}/read")
    prompt(b)
    b.post(f"/v1/sessions/{DONE}/close", {})
    assert {c[:2] for c in b.runner.calls} == {("agent", "list"), ("tab", "list"), ("agent", "read"), ("agent", "prompt"),
                                              ("pane", "close")}


def start_replies(directory: Path, model: str | None, started: Outcome | None = None) -> Replies:
    argv = ["agent", "start", "bridge-capture", "--kind", "claude", "--pane", PANE, "--timeout", "5000"]
    return {
        ("tab", "create", "--cwd", str(directory), "--label", "bridge-capture", "--no-focus"): ok("tab_create.json"),
        tuple(argv + (["--", "--model", model] if model else [])): started or ok("agent_start.json"),
    }


def start(b: Bridge, directory: object, label: object = "bridge-capture", **more: object) -> tuple[int, dict[str, object]]:
    res = b.post("/v1/sessions", {"dir": directory, "label": label, **more})
    return res.status, res.body


def test_start_makes_a_tab_in_the_directory_and_starts_claude_in_it(tmp_path: Path) -> None:
    proj = tmp_path / "proj"
    proj.mkdir()
    b = made(tmp_path, start_replies(proj, "haiku"), drop=(DONE,), roots=(str(tmp_path),))
    status, body = start(b, str(proj), model="haiku")
    assert status == 200
    assert body == {"id": DONE, "label": "bridge-capture", "dir": "bridge-capture-dir", "status": "done", "seq": 1631,
                    "last_typed_at": None}
    assert b.pauses == []


def test_start_without_a_model_passes_no_model(tmp_path: Path) -> None:
    proj = tmp_path / "proj"
    proj.mkdir()
    b = made(tmp_path, start_replies(proj, None), drop=(DONE,), roots=(str(tmp_path),))
    assert start(b, str(proj))[0] == 200
    assert "--model" not in b.runner.calls[-1]


@pytest.mark.parametrize("where", ["outside", "dotdot", "symlink", "new_under_symlink",
                                   "dangling_symlink", "relative", "new_outside", "file", "under_file"])
def test_start_refuses_a_directory_not_under_a_root_and_creates_nothing(tmp_path: Path, where: str) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (tmp_path / "other").mkdir()
    (root / "f").write_text("x")
    (root / "link").symlink_to(tmp_path / "other")
    (root / "dangling").symlink_to(tmp_path / "gone")
    target = {"outside": str(tmp_path / "other"), "dotdot": str(root / ".." / "other"),
              "symlink": str(root / "link"),
              "new_under_symlink": str(root / "link" / "new"), "dangling_symlink": str(root / "dangling"),
              "relative": "root", "new_outside": str(tmp_path / "new"), "file": str(root / "f"),
              "under_file": str(root / "f" / "inside")}[where]
    b = made(tmp_path, drop=(DONE,), roots=(str(root),))
    before = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*") if "state" not in p.parts)
    assert start(b, target) == (403, {"error": "dir_not_allowed"})
    assert not any(c[0] == "tab" and c[1] == "create" for c in b.runner.calls)
    assert sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*") if "state" not in p.parts) == before


def test_start_creates_a_new_folder_under_a_root_and_starts_the_session_in_it(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    new = root / "loaf" / "bench"
    b = made(tmp_path, start_replies(new, None), drop=(DONE,), roots=(str(root),))
    assert start(b, str(new))[0] == 200
    assert new.is_dir()


def test_start_creates_nothing_when_the_label_is_taken(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    b = made(tmp_path, roots=(str(root),))
    taken = [a for a in json.loads(json.dumps(b.get("/v1/sessions").body))["sessions"]][0]["label"]
    assert start(b, str(root / "new"), taken) == (409, {"error": "label_taken"})
    assert not (root / "new").exists()


@pytest.mark.parametrize("label", ["Upper", "1abc", "has space", "", "a" * 33, "x;rm", "-x", 5, None])
def test_start_refuses_a_label_herdr_would_not_name_an_agent(tmp_path: Path, label: object) -> None:
    proj = tmp_path / "proj"
    proj.mkdir()
    b = made(tmp_path, roots=(str(tmp_path),))
    assert start(b, str(proj), label) == (400, {"error": "bad_request"})
    assert b.runner.calls == []


@pytest.mark.parametrize("model", ["--dangerously-skip-permissions", "-x", "a b", "", "x" * 65, 5])
def test_start_refuses_a_model_that_could_be_a_flag(tmp_path: Path, model: object) -> None:
    proj = tmp_path / "proj"
    proj.mkdir()
    b = made(tmp_path, roots=(str(tmp_path),))
    assert start(b, str(proj), model=model) == (400, {"error": "bad_request"})
    assert b.runner.calls == []


def test_start_refuses_unknown_fields_and_a_label_in_use(tmp_path: Path) -> None:
    proj = tmp_path / "proj"
    proj.mkdir()
    b = made(tmp_path, roots=(str(tmp_path),))
    assert start(b, str(proj), cwd="/") == (400, {"error": "bad_request"})
    assert start(b, str(proj), "bridge-capture") == (409, {"error": "label_taken"})
    assert not any(c[0] == "tab" and c[1] == "create" for c in b.runner.calls)


def test_a_start_that_fails_closes_the_tab_it_made(tmp_path: Path) -> None:
    proj = tmp_path / "proj"
    proj.mkdir()
    extra = dict(start_replies(proj, None, failed("agent_start_timeout.err")))
    extra[("tab", "close", "w5H:tK")] = ok("pane_close.json")
    b = made(tmp_path, extra, drop=(DONE,), roots=(str(tmp_path),))
    assert start(b, str(proj)) == (504, {"error": "unconfirmed"})
    assert b.runner.calls[-1] == ("tab", "close", "w5H:tK")


def test_a_start_that_timed_out_also_closes_its_tab_and_logs_a_failed_cleanup(tmp_path: Path) -> None:
    proj = tmp_path / "proj"
    proj.mkdir()
    extra = dict(start_replies(proj, None))
    extra[next(k for k in extra if k[0] == "agent")] = HerdrTimeout("agent")
    extra[("tab", "close", "w5H:tK")] = failed("tab_not_found.err")
    b = made(tmp_path, extra, drop=(DONE,), roots=(str(tmp_path),))
    assert start(b, str(proj))[0] == 504
    assert "call=start_cleanup status=failed" in b.log.lines


def test_a_start_waits_for_the_agent_to_report_a_state(tmp_path: Path) -> None:
    proj = tmp_path / "proj"
    proj.mkdir()
    lists = [listing(drop=(DONE,)), listing({DONE: "unknown"}), listing({DONE: "unknown"}), listing()]
    b = made(tmp_path, {**start_replies(proj, None), LIST: lists}, roots=(str(tmp_path),))
    assert start(b, str(proj))[0] == 200
    assert b.pauses == [0.5, 0.5]


def test_an_agent_that_never_reports_a_state_is_closed_and_unconfirmed(tmp_path: Path) -> None:
    proj = tmp_path / "proj"
    proj.mkdir()
    lists = [listing(drop=(DONE,)), listing({DONE: "unknown"})]
    extra = {**start_replies(proj, None), LIST: lists, ("tab", "close", "w5H:tK"): ok("pane_close.json")}
    b = made(tmp_path, extra, roots=(str(tmp_path),))
    assert start(b, str(proj)) == (504, {"error": "unconfirmed"})
    assert b.pauses == [0.5] * 4
    assert b.runner.calls[-1] == ("tab", "close", "w5H:tK")


def test_the_call_log_has_ids_status_and_timing_and_never_text_paths_or_people(tmp_path: Path) -> None:
    proj = tmp_path / "secretdir"
    proj.mkdir()
    b = made(tmp_path, {**start_replies(proj, None), ("agent", "prompt", PANE, "the private words"): ok("agent_prompt.json")},
             drop=(DONE,), roots=(str(tmp_path),))
    start(b, str(proj))
    b.runner.replies[LIST] = listing()
    prompt(b, text="the private words")
    b.get("/v1/sessions", authorization="Bearer wrong")
    log = "\n".join(b.log.lines)
    for secret in ("private words", "secretdir", str(tmp_path), "bridge-capture", DONE, "t0ken", "Bearer"):
        assert secret not in log, secret
    start_line, prompt_line, refused = b.log.lines
    assert start_line.startswith(f"call=start session={digest8(DONE)} status=200 ms=")
    assert prompt_line.startswith(f"call=prompt session={digest8(DONE)} status=200 ms=")
    assert " bytes=" in prompt_line
    assert refused.startswith("call=unknown session=- status=401") and refused.endswith("error=bad_token")


def test_a_refused_prompt_is_logged_under_its_call_with_the_code(tmp_path: Path) -> None:
    b = made(tmp_path, statuses={DONE: "working"})
    prompt(b)
    assert b.log.lines[0].startswith(f"call=prompt session={digest8(DONE)} status=409")
    assert b.log.lines[0].endswith("error=busy")
