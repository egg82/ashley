"""Inference's log lines: `inference.call` per call made and `inference.route_skipped` per route skipped with their
documented fields, and never a prompt, a system prompt or a reply in any log record, on any path."""

import logging
from collections.abc import Iterator

import pytest
from ashley import logs
from ashley.inference.inference import InferenceRefused, InferenceUnavailable
from ashley.inference.model import Usage
from ashley.inference.reply import Reply
from conversations_support import events
from inference_support import (Clock, FakeLedger, FakeProvider, Step, fail, ok, prompt, refuse, route, router,
                               settle, table)

MARK = "zqPLANTED4417"


@pytest.fixture
def debug_logging() -> Iterator[None]:
    logs.setup({"LOG_LEVEL": "DEBUG"})
    yield
    logs.setup({})


def test_a_call_made_logs_kind_provider_model_outcome_tokens_and_duration(capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    clock = Clock()
    usage = Usage(input_tokens=1234, output_tokens=567)
    inference = router(table([route("alpha", "m1")]), [FakeProvider("alpha", [ok(usage=usage, seconds=0.25)], clock)],
                       clock=clock)
    capsys.readouterr()
    settle(inference.generate("brainstorm", prompt("hello"), Reply))
    lines = events(capsys.readouterr().out, "inference.call")
    assert len(lines) == 1
    line = lines[0]
    assert {"brainstorm", "alpha", "m1", "ok"} <= set(line.values())
    assert line["duration_ms"] == "250"
    assert {"1234", "567", "1801"} & set(line.values()), "the token counts are logged"


def test_a_failed_call_logs_the_providers_reason_and_an_ok_call_none(capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    inference = router(table([route("alpha"), route("beta", "m2")]),
                       [FakeProvider("alpha", [fail("invalid_output")]), FakeProvider("beta", [ok("fine")])])
    capsys.readouterr()
    settle(inference.generate("chat", prompt("hi"), Reply))
    failed, answered = events(capsys.readouterr().out, "inference.call")
    assert failed["reason"] == "invalid_output (status 000)"
    assert "reason" not in answered


def test_each_call_made_is_one_line_with_its_own_outcome(capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    a = FakeProvider("alpha", [fail("unavailable")])
    b = FakeProvider("beta", [refuse()])
    capsys.readouterr()
    with pytest.raises(InferenceRefused):
        settle(router(table([route("alpha"), route("beta", "m2"), route("gamma")]), [a, b, FakeProvider("gamma")])
               .generate("command", prompt("hi"), Reply))
    lines = events(capsys.readouterr().out, "inference.call")
    assert [(ln["provider"], ln["model"], ln["outcome"]) for ln in lines] == [
        ("alpha", "m1", "unavailable"), ("beta", "m2", "refused")]
    assert all(ln["task"] == "command" for ln in lines)


def test_a_route_skipped_logs_kind_provider_model_and_why_and_is_not_a_call(
        capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    a = FakeProvider("alpha", [fail("unavailable")])
    inference = router(table([route("ghost", "gm"), route("alpha", "am"), route("beta")]),
                       [a, FakeProvider("beta", [ok("fine")])])
    capsys.readouterr()
    settle(inference.generate("chat", prompt("hi"), Reply))
    first = capsys.readouterr().out
    settle(inference.generate("command", prompt("hi"), Reply))
    second = capsys.readouterr().out
    unwired = events(first, "inference.route_skipped")
    assert [(ln["task"], ln["provider"], ln["model"], ln["reason"]) for ln in unwired] == [
        ("chat", "ghost", "gm", "unwired")]
    resting = events(second, "inference.route_skipped")
    assert [(ln["task"], ln["provider"], ln["model"], ln["reason"]) for ln in resting] == [
        ("command", "ghost", "gm", "unwired"), ("command", "alpha", "am", "resting")]
    assert [ln["provider"] for ln in events(first, "inference.call")] == ["alpha", "beta"]
    assert [ln["provider"] for ln in events(second, "inference.call")] == ["beta"]


def test_a_failing_ledger_is_logged_once_per_lost_row(capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    inference = router(table([route("alpha"), route("beta")]),
                       [FakeProvider("alpha", [fail("error")]), FakeProvider("beta")],
                       FakeLedger(fail_with=RuntimeError(f"insert failed {MARK}")))
    capsys.readouterr()
    settle(inference.generate("chat", prompt("hi"), Reply))
    out = capsys.readouterr().out
    assert len(events(out, "inference.spend_unrecorded")) == 2
    assert MARK not in out, "an exception's message is never written"


# --- no prompt or reply text, anywhere ---------------------------------------------------------------------------


def everything_logged(out: str, caplog: pytest.LogCaptureFixture) -> str:
    """The stdout lines plus every record's raw message, arguments, fields and exception text, so a logger that
    writes content in a way the logfmt formatter happens to drop is still caught."""
    parts = [out]
    for rec in caplog.records:
        parts += [str(rec.msg), str(rec.args), rec.getMessage(), str(getattr(rec, "fields", ""))]
        if rec.exc_info and rec.exc_info[1] is not None:
            parts.append(str(rec.exc_info[1]))
    return "\n".join(parts)


def leaky_scenario() -> None:
    """Every path through generate, with the marker in the system prompts, the messages and the replies."""
    system = {"default": f"system {MARK}", "tuned": f"tuned {MARK}"}
    given = prompt(f"first {MARK}", f"second {MARK}", f"third {MARK}", system=system)
    unavailable = FakeProvider("alpha", [fail("unavailable")])
    invalid = FakeProvider("beta", [fail("invalid_output", Usage(5, 5))])
    answering = FakeProvider("gamma", [Step({"spoken": f"spoken {MARK}", "text": f"text {MARK}"})])
    refusing = FakeProvider("delta", [refuse(Usage(1, 1))])
    broken = FakeLedger(fail_with=RuntimeError("ledger down"))
    wide = [unavailable, invalid, answering, refusing]
    routes = [route("ghost"), route("alpha", variant="tuned"), route("beta"), route("gamma")]
    inference = router(table(routes), wide, broken)
    for _ in range(2):   # the second pass skips the resting provider
        assert settle(inference.generate("chat", given, Reply)).text == f"text {MARK}"
    refuser = router(table([route("delta")]), wide)
    with pytest.raises(InferenceRefused):
        settle(refuser.generate("chat", given, Reply))
    with pytest.raises(InferenceUnavailable):
        settle(router(table([route("beta")]), wide).generate("chat", given, Reply))
    with pytest.raises(InferenceUnavailable):
        settle(router(table([route("ghost")]), wide).generate("chat", given, Reply))


def test_no_prompt_or_reply_text_reaches_any_log_line(
        debug_logging: None, capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    capsys.readouterr()
    leaky_scenario()
    out = capsys.readouterr().out
    assert len(events(out, "inference.call")) >= 6, "control: the calls were logged"
    assert len(events(out, "inference.route_skipped")) >= 3, "control: the skips were logged"
    assert len(events(out, "inference.spend_unrecorded")) >= 1, "control: the lost rows were logged"
    logged = everything_logged(out, caplog)
    assert MARK not in logged
