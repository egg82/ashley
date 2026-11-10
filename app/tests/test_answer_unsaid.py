"""A closing step that yields nothing to deliver is asked again once, and if it is still empty the turn answers with the
fixed line in `unsaid.json`, so a person is never left with nothing. What the medium delivers is what counts."""

import asyncio
import logging
from dataclasses import replace

import pytest
from ashley import logs
from ashley.channels import inflight, respond as respond_module
from ashley.channels import unsaid
from ashley.channels.respond import failed_later, respond
from ashley.conversations.conversations import ConversationClosed
from ashley.inference.model import ToolCall, ToolResult
from ashley.inference.reply import Reply
from respond_support import ALANA, Fakes, calls, inbound, wired as wired

TEXTUAL = inbound(thread="web", speaker_id=ALANA.id, kind="chat")
SPOKEN = inbound(thread="device:7", speaker_id=ALANA.id, medium="spoken")


def say(text: str, spoken: str | None = None) -> Reply:
    return Reply(spoken=text if spoken is None else spoken, text=text)


EMPTY = say("")


@pytest.fixture(autouse=True)
def one_round(monkeypatch: pytest.MonkeyPatch) -> None:
    """Her second step is the closing one, under choice `none`."""
    for kind in ("chat", "command"):
        monkeypatch.setitem(respond_module.LIMITS, kind, replace(respond_module.LIMITS[kind], max_tool_rounds=1))


def hers(wired: Fakes) -> list[str]:
    return [t.text for t in wired.conversations.added if t.author == "ashley"]


def test_the_shipped_line_is_a_sentence() -> None:
    assert unsaid.LINE.strip() and unsaid.LINE == unsaid.LINE.strip()


def test_an_empty_closing_answer_is_asked_again_under_choice_none(wired: Fakes) -> None:
    wired.inference.script = [calls("lights"), EMPTY, say("Done.")]
    out = asyncio.run(respond(TEXTUAL))
    assert out.body == "Done." and hers(wired) == ["Done."]
    assert [p.tool_choice for p in wired.inference.prompts] == ["auto", "none", "none"]
    note = wired.inference.prompts[2].messages[-1]
    assert (getattr(note, "author", None), getattr(note, "text", None)) == ("person", unsaid.ASK.text)


def noted(wired: Fakes) -> list[bool]:
    """For each step asked, whether its last message is the wrap-up note."""
    return [getattr(p.messages[-1], "text", None) == unsaid.ASK.text for p in wired.inference.prompts]


def test_the_closing_step_after_the_last_round_carries_the_wrap_up_note(wired: Fakes) -> None:
    wired.inference.script = [calls("lights"), say("Done.")]
    asyncio.run(respond(TEXTUAL))
    assert [p.tool_choice for p in wired.inference.prompts] == ["auto", "none"]
    assert noted(wired) == [False, True]


def test_the_closing_step_at_the_deadline_carries_the_wrap_up_note(
        wired: Fakes, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(respond_module.LIMITS, "chat", replace(respond_module.LIMITS["chat"], max_tool_rounds=5,
                                                               deadline_s=0.3))
    real = wired.tools.call

    async def slow(call: ToolCall) -> ToolResult:
        await asyncio.sleep(0.4)
        return await real(call)

    monkeypatch.setattr(wired.tools, "call", slow)
    wired.inference.script = [calls("lights"), say("Done.")]
    asyncio.run(respond(TEXTUAL))
    assert [p.tool_choice for p in wired.inference.prompts] == ["auto", "none"]
    assert noted(wired) == [False, True]


def test_a_step_that_closes_with_no_lookups_made_carries_no_note(wired: Fakes, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(respond_module.LIMITS, "chat", replace(respond_module.LIMITS["chat"], max_tool_rounds=0))
    wired.inference.script = [say("Hi.")]
    asyncio.run(respond(TEXTUAL))
    assert noted(wired) == [False]


def test_an_empty_closing_answer_is_wrapped_up_with_the_note_once(wired: Fakes) -> None:
    wired.inference.script = [calls("lights"), EMPTY, say("Done.")]
    asyncio.run(respond(TEXTUAL))
    assert wired.inference.prompts[2].messages.count(unsaid.ASK) == 1 and noted(wired) == [False, True, True]


def test_a_closing_answer_empty_twice_is_the_fixed_line_and_is_stored(wired: Fakes) -> None:
    wired.inference.script = [calls("lights"), EMPTY, EMPTY]
    out = asyncio.run(respond(TEXTUAL))
    assert out.body == unsaid.LINE and hers(wired) == [unsaid.LINE]
    assert len(wired.inference.prompts) == 3


def test_a_blank_answer_is_empty_too(wired: Fakes) -> None:
    wired.inference.script = [calls("lights"), say("  \n"), say("\t")]
    assert asyncio.run(respond(TEXTUAL)).body == unsaid.LINE


def test_text_filled_and_spoken_empty_is_an_answer_on_a_text_medium(wired: Fakes) -> None:
    wired.inference.script = [say("Fine.", spoken="")]
    assert asyncio.run(respond(TEXTUAL)).body == "Fine."
    assert len(wired.inference.prompts) == 1


def test_spoken_filled_and_text_empty_is_empty_on_a_text_medium(wired: Fakes) -> None:
    wired.inference.script = [calls("lights"), say("", spoken="I did it."), say("Done.")]
    assert asyncio.run(respond(TEXTUAL)).body == "Done."


def test_text_filled_and_spoken_empty_is_empty_on_a_spoken_medium(wired: Fakes) -> None:
    wired.inference.script = [calls("lights"), say("I did it.", spoken=""), say("Done.")]
    assert asyncio.run(respond(SPOKEN)).body == "Done."


def test_an_empty_answer_under_auto_is_asked_again_too_as_a_wrap_up_under_choice_none(
        wired: Fakes, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(respond_module.LIMITS, "chat", replace(respond_module.LIMITS["chat"], max_tool_rounds=3))
    wired.inference.script = [EMPTY, say("Hi.")]
    out = asyncio.run(respond(TEXTUAL))
    assert out.body == "Hi." and len(wired.inference.prompts) == 2
    assert wired.inference.prompts[1].tool_choice == "none"
    assert getattr(wired.inference.prompts[1].messages[-1], "text", None) == unsaid.ASK.text


def test_the_wrap_up_note_says_no_more_lookups_and_to_say_what_is_missing() -> None:
    assert unsaid.ASK.author == "person" and "no more" in unsaid.ASK.text and "need" in unsaid.ASK.text


def test_an_answer_with_text_is_not_asked_again(wired: Fakes) -> None:
    wired.inference.script = [calls("lights"), say("Done.")]
    asyncio.run(respond(TEXTUAL))
    assert len(wired.inference.prompts) == 2


def test_the_log_names_the_case_without_the_words(wired: Fakes, caplog: pytest.LogCaptureFixture) -> None:
    logs.setup()
    caplog.set_level(logging.INFO, logger="ashley.tools")
    wired.inference.script = [calls("lights"), EMPTY, EMPTY]
    asyncio.run(respond(TEXTUAL))
    lines = [r.getMessage() for r in caplog.records if "respond.reply_empty" in r.getMessage()]
    assert lines and all("Done" not in ln for ln in lines)


@pytest.mark.parametrize("error,cause,check", [
    (inflight.Unstored(ValueError("a turn has text")), "ValueError", "a turn has text"),
    (inflight.Unstored(ConversationClosed(4)), "ConversationClosed", ""),
])
def test_a_turn_that_could_not_be_stored_logs_its_cause_and_the_check(
        error: Exception, cause: str, check: str, capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    failed_later(error, 0.0)
    [line] = [ln for ln in capsys.readouterr().out.splitlines() if "respond.failed" in ln]
    assert "reason=unstorable" in line and f"cause={cause}" in line
    assert (f'check="{check}"' in line) if check else ("check=" not in line)
