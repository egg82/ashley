"""`step`'s spend rows and log lines: one row and one `inference.call` per call made, `ok` for a call that asked for
tools, `tool_calls` the number asked for, and no tool name, argument, result or description in any log record."""

import logging
from collections.abc import Iterator

import pytest
from ashley import logs
from ashley.inference.inference import InferenceRefused, InferenceUnavailable
from ashley.inference.model import Message, SystemPrompt, ToolCall, ToolCalls, ToolResult, ToolResults, ToolSpec
from ashley.inference.reply import Reply
from conversations_support import events
from inference_support import USAGE, USAGE_COST, Clock, FakeLedger, outcomes, route, router, settle, table
from inference_tools_support import broke, call, declined, one_round, provider, say, tool_prompt, want
from ashley.inference.model import Prompt

MARK = "zqPLANTED5521"
ASK = Message("person", "turn it on")


@pytest.fixture
def debug_logging() -> Iterator[None]:
    logs.setup({"LOG_LEVEL": "DEBUG"})
    yield
    logs.setup({})


def test_a_call_that_asked_for_tools_is_one_ok_row_with_its_usage_and_cost() -> None:
    ledger = FakeLedger()
    clock = Clock()
    a = provider("alpha", want(call("c1"), call("c2", "weather"), seconds=0.25), clock=clock)
    settle(router(table([route("alpha", "m2")]), [a], ledger, clock).step("brainstorm", tool_prompt(ASK), Reply))
    assert len(ledger.rows) == 1
    row = ledger.rows[0]
    assert (row.task, row.provider, row.model, row.outcome) == ("brainstorm", "alpha", "m2", "ok")
    assert row.usage == USAGE and row.cost_usd == USAGE_COST and row.duration_ms == 250


def test_a_reply_is_one_ok_row() -> None:
    ledger = FakeLedger()
    settle(router(table([route("alpha")]), [provider("alpha", say())], ledger).step("chat", tool_prompt(ASK), Reply))
    assert outcomes(ledger) == [("alpha", "m1", "ok")]


def test_every_call_made_is_a_row_and_skips_are_not() -> None:
    ledger = FakeLedger()
    a, b = provider("a", broke("unavailable")), provider("b", want(call("bad", "ghost")), say("last"))
    inference = router(table([route("ghost"), route("a"), route("b"), route("b", "m2")]), [a, b], ledger)
    assert settle(inference.step("chat", tool_prompt(ASK), Reply)) == Reply(spoken="last", text="last")
    assert outcomes(ledger) == [("a", "m1", "unavailable"), ("b", "m1", "invalid_output"), ("b", "m2", "ok")]


def test_a_refused_step_is_one_refused_row() -> None:
    ledger = FakeLedger()
    with pytest.raises(InferenceRefused):
        settle(router(table([route("a")]), [provider("a", declined())], ledger).step("chat", tool_prompt(ASK), Reply))
    assert outcomes(ledger) == [("a", "m1", "refused")]


def test_a_failing_ledger_does_not_cost_the_caller_the_tool_calls(capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    ledger = FakeLedger(fail_with=RuntimeError(f"insert failed {MARK}"))
    inference = router(table([route("a")]), [provider("a", want(call()))], ledger)
    capsys.readouterr()
    assert settle(inference.step("chat", tool_prompt(ASK), Reply)) == ToolCalls((call(),))
    out = capsys.readouterr().out
    assert len(events(out, "inference.spend_unrecorded")) == 1 and MARK not in out


def test_the_call_line_carries_the_number_of_tool_calls_asked_for(capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    a = provider("a", want(call("1"), call("2"), call("3", "weather")), say())
    inference = router(table([route("a")]), [a])
    capsys.readouterr()
    settle(inference.step("chat", tool_prompt(ASK), Reply))
    settle(inference.step("chat", one_round(), Reply))
    lines = events(capsys.readouterr().out, "inference.call")
    assert [ln["outcome"] for ln in lines] == ["ok", "ok"]
    assert [ln["tool_calls"] for ln in lines] == ["3", "0"]
    assert all({"task", "provider", "model", "duration_ms"} <= set(ln) for ln in lines)


def test_generate_calls_log_zero_tool_calls_or_omit_the_field(capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    inference = router(table([route("a")]), [provider("a", say())])
    capsys.readouterr()
    settle(inference.generate("chat", tool_prompt(ASK, tools=()), Reply))
    (line,) = events(capsys.readouterr().out, "inference.call")
    assert line.get("tool_calls", "0") == "0"


def test_skipped_routes_are_logged_as_for_generate(capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    inference = router(table([route("ghost", "gm"), route("a")]), [provider("a", say())])
    capsys.readouterr()
    settle(inference.step("command", tool_prompt(ASK), Reply))
    out = capsys.readouterr().out
    (skip,) = events(out, "inference.route_skipped")
    assert (skip["task"], skip["provider"], skip["model"], skip["reason"]) == ("command", "ghost", "gm", "unwired")


# --- no tool name, argument, result or description, anywhere -------------------------------------------------------


def everything_logged(out: str, caplog: pytest.LogCaptureFixture) -> str:
    """The stdout lines plus every record's raw message, arguments, fields and exception text."""
    parts = [out]
    for rec in caplog.records:
        parts += [str(rec.msg), str(rec.args), rec.getMessage(), str(getattr(rec, "fields", ""))]
        if rec.exc_info and rec.exc_info[1] is not None:
            parts.append(str(rec.exc_info[1]))
    return "\n".join(parts)


def leaky_prompt(tools: tuple[ToolSpec, ...], with_results: bool) -> Prompt:
    first = ToolCall(f"id{MARK}", f"known{MARK}", {f"key{MARK}": f"value{MARK}"})
    entries: tuple[Message | ToolCalls | ToolResults, ...] = (Message("person", f"text {MARK}"),)
    if with_results:
        entries += (ToolCalls((first,)), ToolResults((ToolResult(first.id, f"result {MARK}", True),)))
    return Prompt({"default": SystemPrompt(f"system {MARK}")}, entries, tools)


def test_no_tool_name_argument_result_or_description_reaches_any_log_line(
        debug_logging: None, capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    spec = ToolSpec(f"known{MARK}", f"describes {MARK}", {"type": "object", "properties": {f"key{MARK}": {}}})
    asked = ToolCall(f"call{MARK}", f"known{MARK}", {f"arg{MARK}": f"argvalue{MARK}"})
    stray = ToolCall(f"call2{MARK}", f"unknown{MARK}", {f"arg{MARK}": MARK})
    a = provider("a", want(asked), want(asked, ToolCall(f"call3{MARK}", f"known{MARK}", {})), want(stray),
                 broke("unavailable"), declined())
    b = provider("b", say(f"reply {MARK}"))
    broken = FakeLedger(fail_with=RuntimeError("ledger down"))
    capsys.readouterr()

    def run(name: str, with_results: bool) -> Reply | ToolCalls:
        inference = router(table([route(name)]), [a, b], broken)
        return settle(inference.step("chat", leaky_prompt((spec,), with_results), Reply))

    run("a", False)
    run("a", True)
    with pytest.raises(InferenceUnavailable):
        run("a", True)   # the stray tool
    with pytest.raises(InferenceUnavailable):
        run("a", True)   # unavailable
    with pytest.raises(InferenceRefused):
        run("a", True)
    run("b", True)
    with pytest.raises(ValueError):
        settle(router(table([route("a")]), [a], broken).generate("chat", leaky_prompt((spec,), True), Reply))
    out = capsys.readouterr().out
    assert len(events(out, "inference.call")) == 6, "control: every call was logged"
    assert any(ln.get("tool_calls") not in (None, "0") for ln in events(out, "inference.call")), "control: tool calls"
    assert len(events(out, "inference.spend_unrecorded")) >= 1, "control: lost rows were logged"
    assert MARK not in everything_logged(out, caplog)


def test_the_probe_sees_a_marker_when_one_is_logged(capsys: pytest.CaptureFixture[str],
                                                    caplog: pytest.LogCaptureFixture) -> None:
    """Control: `everything_logged` finds a planted marker, so its absence above means something."""
    logs.setup()
    caplog.set_level(logging.DEBUG)
    logs.info(logging.getLogger("ashley.inference"), "inference.planted", note=MARK)
    assert MARK in everything_logged(capsys.readouterr().out, caplog)
