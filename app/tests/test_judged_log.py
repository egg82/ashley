"""The two log events of a judged call (`ashley.tools.outside_judging`): `outside.judged` names the conversation, turn, tool,
tier, decision and reason enum and the time the verdict took; `outside.judge_failed` names the error's class and never its text."""

import asyncio
import logging
from collections.abc import Generator, Mapping, Sequence
from types import SimpleNamespace
from typing import Any

import pytest
from ashley import services
from ashley.inference.model import ToolCall, ToolResult
from ashley.tools import outside_config, outside_judging
from ashley.tools.action_judge import ActionJudge, Verdict, View
from ashley.tools.tools import Catalogue, Tools

TURN = (40, 100)
PLANT = "PLANTED-error-text-5b2e"


class Stub(ActionJudge):
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error

    async def decide(self, words: Sequence[str], view: View) -> Verdict:
        if self.error is not None:
            raise self.error
        return Verdict("run", "asked_directly", "You asked.")


class Source(Tools):
    async def catalogue(self) -> Catalogue:
        return Catalogue((), None)

    async def call(self, call: ToolCall) -> ToolResult:
        return ToolResult(call.id, "ok")


class Saved:
    def __init__(self) -> None:
        self.verdicts: dict[str, Verdict] = {}

    async def judged(self, call_id: str, verdict: Verdict) -> None:
        self.verdicts[call_id] = verdict

    def judgement(self, call_id: str) -> Verdict | None:
        return self.verdicts.get(call_id)


async def said() -> Sequence[str]:
    return ("do it",)


@pytest.fixture(autouse=True)
def judge_unwired() -> Generator[None]:
    yield
    services.unregister(ActionJudge)


def events(caplog: pytest.LogCaptureFixture, name: str) -> list[Mapping[str, Any]]:
    return [dict(getattr(r, "fields", {})) for r in caplog.records if r.getMessage() == name]


def judge(error: Exception | None = None) -> None:
    services.register(ActionJudge, Stub(error))
    call = ToolCall("c1", "claude_prompt", {})
    asyncio.run(outside_judging.verdict_on(call, None, "judged", Source(), said, Saved(), outside_config.load(), TURN))


def test_the_judged_event_names_the_turn_the_tier_and_the_reason(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    judge()
    [fields] = events(caplog, "outside.judged")
    assert (fields["conversation"], fields["turn"], fields["tool"], fields["tier"]) == (40, 100, "claude_prompt", "judged")
    assert (fields["decision"], fields["reason"]) == ("run", "asked_directly")


def test_the_judged_event_carries_the_time_the_verdict_took(caplog: pytest.LogCaptureFixture,
                                                          monkeypatch: pytest.MonkeyPatch) -> None:
    ticks = iter([10.0, 10.25])
    monkeypatch.setattr(outside_judging, "time", SimpleNamespace(monotonic=lambda: next(ticks)))
    caplog.set_level(logging.INFO)
    judge()
    [fields] = events(caplog, "outside.judged")
    assert fields["duration_ms"] == 250


def test_a_failure_is_logged_by_its_class_and_never_its_text(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    judge(RuntimeError(PLANT))
    [fields] = events(caplog, "outside.judge_failed")
    assert fields["error"] == "RuntimeError" and PLANT not in repr([r.__dict__ for r in caplog.records])
