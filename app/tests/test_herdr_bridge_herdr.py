"""The `herdr` CLI wrapper against the captured answers, and the real subprocess runner."""

import stat
from pathlib import Path

import pytest
from herdr_bridge.herdr import Herdr, HerdrError, decode, parse_agent
from herdr_bridge.runner import HerdrMissing, HerdrTimeout, Outcome, SubprocessRunner

from herdr_bridge_support import THROWAWAY, FakeHerdr, captured, failed, ok


def test_the_captured_list_parses_to_claude_sessions() -> None:
    agents = Herdr(FakeHerdr({("agent", "list"): ok("agent_list.json")})).agents()
    assert [a.status for a in agents] == ["working", "done", "idle", "idle", "idle"]
    done = agents[1]
    assert (done.session_id, done.pane_id, done.tab_id, done.name) == (THROWAWAY, "w5H:pK", "w5H:tK", "bridge-capture")
    assert (done.seq, done.revision, done.cwd.rsplit("/", 1)[-1]) == (1631, 4, "bridge-capture-dir")
    assert agents[3].name is None


def test_an_agent_that_is_not_claude_or_has_no_session_is_not_listed() -> None:
    base = {"pane_id": "w1:p1", "tab_id": "w1:t1", "agent_status": "idle"}
    session = {"agent_session": {"value": "abc"}}
    assert parse_agent({**base, "agent": "codex", **session}) is None
    assert parse_agent({**base, "agent": "claude"}) is None
    assert parse_agent({**base, "agent": "claude", "agent_session": {}}) is None
    assert parse_agent({"agent": "claude", **session}) is None


def test_a_status_herdr_adds_later_reads_as_unknown() -> None:
    agent = parse_agent({"agent": "claude", "pane_id": "p", "tab_id": "t", "agent_status": "napping",
                         "agent_session": {"value": "abc"}})
    assert agent is not None and agent.status == "unknown"


def test_tab_labels_by_tab_id() -> None:
    labels = Herdr(FakeHerdr({("tab", "list"): ok("tab_list.json")})).tab_labels()
    assert labels["w5H:tH"] == "app-2" and labels["w63:t1"] == "1"


def test_tab_create_and_agent_start_read_the_ids_herdr_returns() -> None:
    created = Herdr(FakeHerdr({("tab", "create", "--cwd", "/d", "--label", "x", "--no-focus"): ok("tab_create.json")})
                    ).tab_create("/d", "x")
    assert (created.tab_id, created.pane_id) == ("w5H:tK", "w5H:pK")


def test_herdr_errors_carry_herdrs_code() -> None:
    with pytest.raises(HerdrError) as e:
        decode(failed("agent_not_found.err"))
    assert e.value.code == "agent_not_found"
    with pytest.raises(HerdrError) as timeout:
        decode(failed("agent_start_timeout.err"))
    assert timeout.value.code == "timeout"
    with pytest.raises(HerdrError) as unreadable:
        decode(Outcome(1, "", "panic: not json"))
    assert unreadable.value.code == "failed"
    with pytest.raises(HerdrError) as garbage:
        decode(Outcome(0, "not json", ""))
    assert garbage.value.code == "bad_output"


def test_a_read_refused_because_the_agent_is_working_falls_back_to_the_visible_screen() -> None:
    history = ("agent", "read", "w5:pC", "--source", "recent-unwrapped", "--lines", "60")
    visible = ("agent", "read", "w5:pC", "--source", "visible", "--lines", "60")
    runner = FakeHerdr({history: failed("agent_read_not_idle.err"), visible: ok("agent_read.txt")})
    assert Herdr(runner).read("w5:pC", 60) == captured("agent_read.txt")
    assert runner.calls == [history, visible]


def test_a_read_refused_for_any_other_reason_is_not_retried() -> None:
    history = ("agent", "read", "w5:pC", "--source", "recent-unwrapped", "--lines", "60")
    runner = FakeHerdr({history: failed("agent_not_found.err")})
    with pytest.raises(HerdrError) as e:
        Herdr(runner).read("w5:pC", 60)
    assert e.value.code == "agent_not_found"
    assert runner.calls == [history]


def test_the_version_is_read_from_the_captured_line_or_unknown() -> None:
    assert Herdr(FakeHerdr({("--version",): ok("version.out")})).version() == "0.9.5"
    assert Herdr(FakeHerdr({("--version",): Outcome(0, "something else entirely\n", "")})).version() is None


def script(tmp_path: Path, body: str) -> SubprocessRunner:
    path = tmp_path / "herdr"
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return SubprocessRunner(str(path))


def test_the_subprocess_runner_returns_code_output_and_arguments_untouched(tmp_path: Path) -> None:
    runner = script(tmp_path, 'printf "%s|" "$@"; echo oops >&2; exit 3\n')
    got = runner.run(["agent", "prompt", "p", "a b; $(x) --wait"], 5)
    assert got == Outcome(3, "agent|prompt|p|a b; $(x) --wait|", "oops\n")


def test_the_subprocess_runner_reports_a_missing_binary_and_a_timeout(tmp_path: Path) -> None:
    with pytest.raises(HerdrMissing):
        SubprocessRunner(str(tmp_path / "nope")).run(["agent", "list"], 5)
    with pytest.raises(HerdrTimeout):
        script(tmp_path, "exec sleep 5\n").run(["agent", "list"], 0.2)


def test_the_captured_files_are_not_empty() -> None:
    assert all(len(captured(n)) > 10 for n in ("agent_list.json", "tab_list.json", "agent_start.json", "status.out"))
