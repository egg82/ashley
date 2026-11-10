"""A reply on a bench is held to its kind's `reply_chars` (`turns.json`): one over it is asked again, with the draft and
what is wrong in view, up to `RESHORTENED` times, and the last one is delivered as it is. A kind with no limit is never
asked."""

import asyncio
from dataclasses import replace

import pytest
from ashley.channels import respond as respond_module
from ashley.channels import tool_loop
from ashley.channels.limits import load
from ashley.channels.respond import respond
from ashley.inference.model import Message, ToolCall, ToolCalls
from ashley.inference.reply import Reply
from respond_support import ALANA, Fakes, inbound, wired as wired

LIMIT = 100
BENCH = replace(inbound(thread="bench:4", speaker_id=ALANA.id, kind="brainstorm"), audience="owner", shared=False,
                place=None, channel="web", bench_id=4)


def say(chars: int) -> Reply:
    text = "x" * chars
    return Reply(spoken=text, text=text)


def limited(monkeypatch: pytest.MonkeyPatch, chars: int = LIMIT) -> None:
    monkeypatch.setitem(respond_module.LIMITS, "brainstorm", replace(respond_module.LIMITS["brainstorm"], reply_chars=chars))


def test_the_shipped_limits_hold_a_bench_reply_and_nothing_else() -> None:
    limits = load()
    assert 0 < limits["brainstorm"].reply_chars < 1000
    assert limits["chat"].reply_chars == 0 and limits["command"].reply_chars == 0


def test_a_bench_reply_over_the_limit_is_asked_again_and_the_short_one_is_delivered(wired: Fakes, monkeypatch: pytest.MonkeyPatch) -> None:
    limited(monkeypatch)
    wired.inference.script = [say(LIMIT + 1), say(LIMIT)]
    out = asyncio.run(respond(BENCH))
    assert out.body == "x" * LIMIT
    again = wired.inference.prompts[1].messages[-2:]
    assert all(isinstance(m, Message) for m in again)
    draft, note = [m for m in again if isinstance(m, Message)]
    assert draft.author == "ashley" and draft.text == "x" * (LIMIT + 1)
    assert note.author == "person" and str(LIMIT) in note.text
    assert [t.text for t in wired.conversations.added if t.author == "ashley"] == ["x" * LIMIT]


def test_a_reply_within_the_limit_is_not_asked_again(wired: Fakes, monkeypatch: pytest.MonkeyPatch) -> None:
    limited(monkeypatch)
    wired.inference.script = [say(LIMIT)]
    asyncio.run(respond(BENCH))
    assert len(wired.inference.prompts) == 1


def test_a_reply_that_stays_long_is_asked_again_a_bounded_number_of_times_then_delivered(wired: Fakes, monkeypatch: pytest.MonkeyPatch) -> None:
    limited(monkeypatch)
    wired.inference.script = [say(LIMIT + n) for n in range(1, tool_loop.RESHORTENED + 2)]
    out = asyncio.run(respond(BENCH))
    assert len(wired.inference.prompts) == tool_loop.RESHORTENED + 1
    assert out.body == "x" * (LIMIT + tool_loop.RESHORTENED + 1)


def test_a_kind_without_a_limit_is_never_asked_again(wired: Fakes) -> None:
    wired.inference.script = [say(5000)]
    out = asyncio.run(respond(inbound(thread="web", speaker_id=ALANA.id, kind="chat")))
    assert len(out.body) == 5000 and len(wired.inference.prompts) == 1


def forced(monkeypatch: pytest.MonkeyPatch) -> None:
    """A bench whose tool rounds are spent after one, so her second step is the forced answer under choice `none`."""
    limited(monkeypatch)
    monkeypatch.setitem(respond_module.LIMITS, "brainstorm", replace(respond_module.LIMITS["brainstorm"], max_tool_rounds=1))


def test_the_forced_answer_is_asked_again_shorter_still_under_choice_none(wired: Fakes, monkeypatch: pytest.MonkeyPatch) -> None:
    forced(monkeypatch)
    wired.inference.script = [ToolCalls((ToolCall("c0", "lights", {}),)), say(LIMIT + 1), say(LIMIT)]
    out = asyncio.run(respond(BENCH))
    assert out.body == "x" * LIMIT
    assert [p.tool_choice for p in wired.inference.prompts] == ["auto", "none", "none"]


def test_the_forced_answer_that_stays_long_is_asked_a_bounded_number_of_times_then_sent(
        wired: Fakes, monkeypatch: pytest.MonkeyPatch) -> None:
    forced(monkeypatch)
    wired.inference.script = [ToolCalls((ToolCall("c0", "lights", {}),)),
                              *[say(LIMIT + n) for n in range(1, tool_loop.RESHORTENED + 2)]]
    out = asyncio.run(respond(BENCH))
    assert len(wired.inference.prompts) == tool_loop.RESHORTENED + 2
    assert out.body == "x" * (LIMIT + tool_loop.RESHORTENED + 1)
