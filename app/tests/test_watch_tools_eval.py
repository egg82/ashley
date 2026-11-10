"""The watch-tools eval's grading and report, from scripted calls: each expectation passes on its call and fails on a
wrong session, a wrong `until`, an extra call or none, and the seed cases are well formed."""

import asyncio
from typing import Any

import pytest
from ashley.evals import watch_tools
from ashley.evals.house import Seat
from ashley.evals.watch_tools import RunResult
from ashley.evals.watch_tools_fakes import SESSIONS, id_of
from ashley.inference.model import ToolCall

K8S, DOCS = id_of("k8s-upgrade"), id_of("docs-pass")


def case(expect: str, session: str = "k8s-upgrade", until: str = "none") -> dict[str, Any]:
    return {"id": "x", "turns": ["t"], "expect": expect, "session": session, "until": until}


def watch(target: str = K8S, **more: Any) -> ToolCall:
    return ToolCall("c", "watch", {"kind": "claude_session", "target": target, **more})


def unwatch(target: str = K8S) -> ToolCall:
    return ToolCall("c", "unwatch", {"kind": "claude_session", "target": target})


GONE: list[list[dict[str, Any]]] = [[{"kind": "gone"}]]


def test_a_watch_case_passes_on_the_session_with_no_until_and_on_exactly_gone() -> None:
    assert watch_tools.passes(case("watch"), [watch()])
    assert watch_tools.passes(case("watch", until="gone"), [watch(until=GONE)])
    assert watch_tools.passes(case("watch", until="gone"), [watch(until=[[{"kind": "gone", "not": False}]])])
    assert watch_tools.passes(case("watch"), [ToolCall("r", "claude_sessions", {}), watch(), watch()])


@pytest.mark.parametrize("calls", [
    [], [watch(DOCS)], [watch(), watch(DOCS)], [watch(until=GONE)], [unwatch()], [watch(), unwatch()],
    [watch(until=[[{"kind": "gone", "not": True}]])], [watch(until=[[{"kind": "equals", "field": "status",
                                                                         "value": "done"}]])],
    [ToolCall("c", "watch", {"kind": "mystery", "target": K8S})]])
def test_a_watch_case_fails_on_none_a_wrong_session_a_wrong_until_or_another_tool(calls: list[ToolCall]) -> None:
    assert not watch_tools.passes(case("watch"), calls)


def test_a_gone_case_fails_without_the_until() -> None:
    assert not watch_tools.passes(case("watch", until="gone"), [watch()])
    assert not watch_tools.passes(case("watch", until="gone"), [watch(until=[[{"kind": "new"}]])])


def test_an_unwatch_case_passes_on_the_session_and_fails_on_another_or_a_watch() -> None:
    assert watch_tools.passes(case("unwatch", "docs-pass"), [unwatch(DOCS)])
    assert not watch_tools.passes(case("unwatch", "docs-pass"), [unwatch(K8S)])
    assert not watch_tools.passes(case("unwatch", "docs-pass"), [unwatch(DOCS), watch(DOCS)])
    assert not watch_tools.passes(case("unwatch", "docs-pass"), [])


def test_a_nothing_case_passes_on_reads_and_fails_on_any_watch_or_unwatch() -> None:
    assert watch_tools.passes(case("nothing"), [])
    assert watch_tools.passes(case("nothing"), [ToolCall("r", "watches", {}), ToolCall("r", "claude_sessions", {})])
    assert not watch_tools.passes(case("nothing"), [watch()])
    assert not watch_tools.passes(case("nothing"), [unwatch()])


def test_the_report_names_each_runs_watch_calls_by_session_label() -> None:
    ran = RunResult("watch-named", True, tuple(watch_tools.describe(c) for c in (watch(until=GONE), unwatch(DOCS))),
                    ("claude_sessions", "watch", "unwatch"), 0, None)
    text = watch_tools.render({"watch-named": [ran]})
    assert "watch(k8s-upgrade,gone) unwatch(docs-pass)" in text and "TOTAL" in text and "1/1" in text


def test_the_seed_cases_cover_what_was_asked_and_name_real_sessions() -> None:
    cases = watch_tools.load()
    assert len({c["id"] for c in cases}) == len(cases)
    assert {c["expect"] for c in cases} == {"watch", "unwatch", "nothing"}
    assert {c["until"] for c in cases if c["expect"] == "watch"} == {"none", "gone"}
    labels = {s.label for s in SESSIONS}
    assert all(c["session"] in labels for c in cases if c["expect"] != "nothing")
    assert all(c["turns"] and all(isinstance(t, str) and t for t in c["turns"]) for c in cases)


def test_an_unknown_case_raises() -> None:
    with pytest.raises(ValueError):
        asyncio.run(watch_tools.run(1, "nope", Seat(1, 1)))
