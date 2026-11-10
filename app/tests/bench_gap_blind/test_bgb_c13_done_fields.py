"""Contract 13: `respond.done` carries `changes` (calls whose spec does not read), `closed` (answer, deadline, window,
stood, wrapped) and `answers`. Through `respond` with a fake clock the tools move."""

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from types import SimpleNamespace

import pytest
from ashley.channels import respond as respond_module
from ashley.channels import turn_tools as turn_tools_module
from ashley.channels.model import Inbound
from ashley.channels.respond import respond
from ashley.inference.model import ToolCall, ToolCalls, ToolResult, ToolSpec
from ashley.inference.reply import Reply
from ashley.tools.tools import Catalogue, Tools
from bgb_support import FINAL, PROMISE, STOOD, START
from bgb_bench_support import BENCH
from contract.inference_support import Clock
from later_support import Logged
from respond_support import Fakes, wired as wired

PEEK = ToolSpec("peek", "look", {"type": "object"}, reads=True, outside=False)
BUILD = ToolSpec("build", "build", {"type": "object"}, reads=False, outside=False, tier="runs")
WEB_BENCH = replace(BENCH, later=True, later_by="turn")


@dataclass
class Slow(Tools):
    clock: Clock
    seconds: float
    called: list[ToolCall] = field(default_factory=list[ToolCall])

    async def catalogue(self) -> Catalogue:
        return Catalogue((PEEK, BUILD), None)

    async def call(self, call: ToolCall) -> ToolResult:
        self.called.append(call)
        self.clock.advance(self.seconds)
        return ToolResult(call.id, "ok")


def builds(n: int) -> list[ToolCalls]:
    return [ToolCalls((ToolCall(f"b{i}", "build", {"i": i}),)) for i in range(n)]


def turn(wired: Fakes, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
         script: Sequence[ToolCalls | Reply], seconds: float = 100.0, inbound: Inbound = WEB_BENCH) -> Logged:
    clock = Clock(START)
    monkeypatch.setattr(respond_module, "time", SimpleNamespace(perf_counter=clock))
    slow = Slow(clock, seconds)

    def for_turn(*_a: object, **_k: object) -> Tools:
        return slow

    monkeypatch.setattr(turn_tools_module, "for_turn", for_turn)
    wired.inference.script.extend(script)
    log = Logged(capsys)
    asyncio.run(respond(inbound))
    return log


def done(log: Logged) -> dict[str, str]:
    (line,) = log.events("respond.done")
    return line


def test_c13_a_plain_answer_closes_as_an_answer_with_no_changes(
        wired: Fakes, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    line = done(turn(wired, monkeypatch, capsys, [FINAL]))
    assert (line["changes"], line["closed"], line["answers"]) == ("0", "answer", "true")


def test_c13_changes_counts_the_calls_whose_spec_does_not_read(
        wired: Fakes, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    mixed = ToolCalls((ToolCall("p", "peek", {}), ToolCall("b0", "build", {"i": 0}), ToolCall("b1", "build", {"i": 1})))
    line = done(turn(wired, monkeypatch, capsys, [mixed, FINAL], seconds=1.0))
    assert line["changes"] == "2" and line["closed"] == "answer"


def test_c13_a_window_taken_then_an_answer_closes_as_an_answer(
        wired: Fakes, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    log = turn(wired, monkeypatch, capsys, [*builds(4), FINAL])
    line = done(log)
    assert (line["changes"], line["closed"], line["answers"]) == ("4", "answer", "true")
    assert len(log.events("respond.window")) == 1 and log.events("respond.deadline") == []


def test_c13_a_close_at_the_deadline_with_no_window_left_is_closed_deadline(
        wired: Fakes, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    log = turn(wired, monkeypatch, capsys, [*builds(9), FINAL])
    line = done(log)
    assert (line["closed"], line["answers"], line["changes"]) == ("deadline", "true", "9")
    assert len(log.events("respond.window")) == 2


def test_c13_a_promise_at_the_close_with_no_window_left_is_closed_stood_and_never_stored(
        wired: Fakes, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    log = turn(wired, monkeypatch, capsys, [*builds(9), PROMISE, STOOD])
    line = done(log)
    assert line["closed"] == "stood" and line["answers"] == "true" and len(log.events("respond.stood")) == 1
    stored = [t.text for t in wired.conversations.added if t.author == "ashley"]
    assert STOOD.text in stored and PROMISE.text not in stored


@pytest.mark.parametrize("script", [[PROMISE, STOOD], [FINAL]])
def test_c15_no_close_is_logged_answers_false(
        wired: Fakes, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
        script: list[Reply]) -> None:
    log = turn(wired, monkeypatch, capsys, [*builds(9), *script] if len(script) > 1 else [*builds(4), *script])
    assert done(log)["answers"] == "true"
