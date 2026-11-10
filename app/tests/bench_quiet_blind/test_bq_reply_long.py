"""A reply on a bench longer than `Limits.reply_chars` is not sent: it is kept as her draft, she is told the limit and
stepped again, `tool_loop.RESHORTENED` times at most, and then the reply goes out as it is. Chat kinds are unaffected."""

import asyncio

import pytest
from ashley.channels import limits, tool_loop
from ashley.channels.respond import respond
from ashley.conversations.model import Kind
from ashley.inference.model import ToolCalls
from pydantic import BaseModel
from bq_support import SECRET, capture, inbound, logged, messages_of, read_by_her, reply, steps
from respond_support import Fakes, calls

LIMIT = limits.load()["brainstorm"].reply_chars
SHORT = reply(40)


def test_the_limits_this_suite_pins_are_the_shipped_ones() -> None:
    assert (LIMIT, tool_loop.RESHORTENED) == (500, 2)


def test_a_reply_of_exactly_the_limit_is_sent_at_once(wired: Fakes, caplog: pytest.LogCaptureFixture) -> None:
    capture(caplog)
    wired.inference.script = [reply(LIMIT)]
    out = asyncio.run(respond(inbound()))
    assert out.body == "x" * LIMIT
    assert steps(wired) == 1
    assert logged(caplog, "respond.reply_long") == []


def test_a_reply_one_over_is_not_sent_and_the_next_one_is(wired: Fakes, caplog: pytest.LogCaptureFixture) -> None:
    capture(caplog)
    wired.inference.script = [reply(LIMIT + 1), SHORT]
    out = asyncio.run(respond(inbound()))
    assert out.body == SHORT.text
    assert steps(wired) == 2
    assert len(logged(caplog, "respond.reply_long")) == 1


def test_the_long_reply_is_kept_as_her_draft_and_she_is_told_the_limit(wired: Fakes) -> None:
    long = reply(LIMIT + 1)
    wired.inference.script = [long, SHORT]
    asyncio.run(respond(inbound()))
    second = wired.inference.prompts[1]
    assert any(m.author == "ashley" and long.text in m.text for m in messages_of(second))
    told = messages_of(second)[-1]
    assert told.author == "person" and str(LIMIT) in told.text
    assert long.text not in told.text


def test_the_refused_draft_is_never_stored_as_her_turn(wired: Fakes) -> None:
    long = reply(LIMIT + 1)
    wired.inference.script = [long, SHORT]
    asyncio.run(respond(inbound()))
    hers = [t for t in wired.conversations.added if t.author == "ashley"]
    assert [t.text for t in hers] == [SHORT.text]


def test_the_log_names_the_case_without_the_words(wired: Fakes, caplog: pytest.LogCaptureFixture) -> None:
    capture(caplog)
    wired.inference.script = [reply(LIMIT + 1).model_copy(update={"text": SECRET * 30}), SHORT]
    asyncio.run(respond(inbound(text="a question nobody should see in a log")))
    assert logged(caplog, "respond.reply_long")
    assert SECRET not in caplog.text and "nobody should see" not in caplog.text


def test_two_long_replies_are_asked_again_and_the_third_step_is_taken(wired: Fakes, caplog: pytest.LogCaptureFixture) -> None:
    capture(caplog)
    wired.inference.script = [reply(LIMIT + 1), reply(LIMIT + 50), SHORT]
    out = asyncio.run(respond(inbound()))
    assert out.body == SHORT.text
    assert steps(wired) == 3 and wired.inference.script == []
    assert len(logged(caplog, "respond.reply_long")) >= 2


def test_the_third_long_reply_goes_out_as_it_is(wired: Fakes, caplog: pytest.LogCaptureFixture) -> None:
    capture(caplog)
    final = reply(LIMIT + 7)
    wired.inference.script = [reply(LIMIT + 1), reply(LIMIT + 2), final]
    out = asyncio.run(respond(inbound()))
    assert out.body == final.text and len(out.body) == LIMIT + 7
    assert steps(wired) == 1 + tool_loop.RESHORTENED and wired.inference.script == []
    assert [t.text for t in wired.conversations.added if t.author == "ashley"] == [final.text]
    assert len(logged(caplog, "respond.reply_long")) >= tool_loop.RESHORTENED


def test_a_third_attempt_that_is_short_is_sent_not_asked_a_fourth_time(wired: Fakes) -> None:
    wired.inference.script = [reply(LIMIT + 1), reply(LIMIT + 1), reply(LIMIT)]
    out = asyncio.run(respond(inbound()))
    assert out.body == "x" * LIMIT and steps(wired) == 3


@pytest.mark.parametrize("kind", ["chat", "command"])
def test_other_kinds_send_a_long_reply_as_it_is(wired: Fakes, caplog: pytest.LogCaptureFixture, kind: Kind) -> None:
    capture(caplog)
    wired.inference.script = [reply(LIMIT * 4)]
    out = asyncio.run(respond(inbound(kind=kind)))
    assert len(out.body) == LIMIT * 4 and steps(wired) == 1
    assert logged(caplog, "respond.reply_long") == []


def test_what_is_measured_is_the_text_not_the_spoken_form(wired: Fakes) -> None:
    wired.inference.script = [reply(LIMIT, spoken="s" * (LIMIT * 3))]
    out = asyncio.run(respond(inbound()))
    assert out.body == "x" * LIMIT and steps(wired) == 1


def test_a_long_reply_after_tool_rounds_is_asked_again_too(wired: Fakes) -> None:
    wired.inference.script = [calls("lights"), reply(LIMIT + 1), SHORT]
    out = asyncio.run(respond(inbound()))
    assert out.body == SHORT.text and steps(wired) == 3
    assert [c.name for c in wired.tools.called] == ["lights"]


def test_each_turn_has_its_own_allowance(wired: Fakes) -> None:
    wired.inference.script = [reply(LIMIT + 1), SHORT, reply(LIMIT + 1), SHORT]
    first = asyncio.run(respond(inbound(text="one")))
    second = asyncio.run(respond(inbound(text="two")))
    assert first.body == second.body == SHORT.text and steps(wired) == 4
    assert read_by_her(wired.inference.prompts[3]).count(str(LIMIT)) >= 1


def test_the_answer_forced_after_the_last_tool_round_is_held_to_the_limit_too(wired: Fakes) -> None:
    rounds = limits.load()["brainstorm"].max_tool_rounds
    script: list[ToolCalls | BaseModel | Exception] = [calls("lights", prefix=f"r{i}") for i in range(rounds)]
    wired.inference.script = [*script, reply(LIMIT + 10), SHORT]
    out = asyncio.run(respond(inbound()))
    assert out.body == SHORT.text
