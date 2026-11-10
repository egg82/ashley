"""channels.respond against fakes of every system it reaches: each numbered step of its contract, the tool loop and
its limit, the errors it raises and what stays stored, and its log lines."""

import asyncio

import pytest
from ashley import logs
from ashley.channels import respond as respond_module
from ashley.channels.limits import Limits
from ashley.channels.respond import RespondRefused, RespondUnavailable, respond
from ashley.inference.inference import InferenceRefused, InferenceUnavailable
from ashley.inference.model import Message, ToolCalls, ToolResults
from ashley.inference.reply import Reply
from contract.conversations_support import events
from respond_support import ALANA, SAM, Fakes, calls, inbound, wired as wired

REPLY = Reply(spoken="It is on.", text="It's **on**.")
MARK = "zqLEAK5521"


def turns(fakes: Fakes) -> list[tuple[str, str, int | None]]:
    conv = next(iter(fakes.conversations.convs.values()))
    return [(t.author, t.text, t.speaker_id) for t in conv.turns]


@pytest.mark.parametrize(("medium", "field"), [("text", REPLY.text), ("spoken", REPLY.spoken)])
def test_the_delivered_field_is_the_body_and_what_is_stored(wired: Fakes, medium: str, field: str) -> None:
    wired.inference.script = [REPLY]
    out = asyncio.run(respond(inbound(medium=medium)))
    assert out.body == field and out.medium == medium
    assert turns(wired) == [("person", "hello", None), ("ashley", field, None)]


def test_one_person_home_on_a_shared_device_is_the_speaker(wired: Fakes) -> None:
    wired.presence.answer = frozenset({SAM.id})
    wired.inference.script = [REPLY]
    asyncio.run(respond(inbound()))
    assert wired.conversations.calls[0] == ("for_thread", (10, "device:7", "command", (SAM.id,)))
    assert turns(wired)[0] == ("person", "hello", SAM.id)
    assert wired.contexts[0].speaker == SAM and wired.contexts[0].home == {SAM.id}
    assert wired.inference.prompts[0].messages == (Message("person", "Sam: hello"),)


@pytest.mark.parametrize(("home", "shared"), [(frozenset({1, 2}), True), (frozenset[int](), True), (None, True),
                                              (frozenset({1}), False)])
def test_otherwise_the_speaker_is_unknown(wired: Fakes, home: frozenset[int] | None, shared: bool) -> None:
    wired.presence.answer = home
    wired.inference.script = [REPLY]
    asyncio.run(respond(inbound(shared=shared)))
    assert wired.contexts[0].speaker is None
    assert wired.inference.prompts[0].messages == (Message("person", "hello"),)


def test_a_named_speaker_wins_and_earlier_turns_are_sent_oldest_first(wired: Fakes) -> None:
    wired.inference.script = [REPLY, REPLY]
    asyncio.run(respond(inbound("first", speaker_id=ALANA.id)))
    asyncio.run(respond(inbound("second", shared=False)))
    assert wired.inference.prompts[1].messages == (
        Message("person", "(Sat 24 Oct 2026 18:00) Alana: first"), Message("ashley", f"(Sat 24 Oct 2026 18:00) {REPLY.text}"),
        Message("person", "second"))


def test_tool_calls_run_in_order_cut_to_the_limit_then_she_must_answer(wired: Fakes,
                                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(respond_module.LIMITS, "command",
                        Limits(max_tool_rounds=2, max_tool_result_chars=300, recent_turns=10, relevant_turns=0))
    wired.tools.result = "abcdefgh" * 100
    wired.inference.script = [calls("lights", "lights"), calls("lights", prefix="d"), REPLY]
    asyncio.run(respond(inbound()))
    prompts = wired.inference.prompts
    assert [p.tool_choice for p in prompts] == ["auto", "auto", "none"]
    assert [c.id for c in wired.tools.called] == ["c0", "c1", "d0"]
    results = [e for e in prompts[2].messages if isinstance(e, ToolResults)]
    seen = [r.content for rs in results for r in rs.results]
    assert len(seen) == 3 and all(c.startswith("[cut: only the first") and len(c) <= 300 for c in seen)
    assert all(p.tools == wired.tools.specs for p in prompts)


def test_tools_under_choice_none_run_nothing_and_are_unavailable(wired: Fakes,
                                                                monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(respond_module.LIMITS, "command",
                        Limits(max_tool_rounds=0, max_tool_result_chars=5, recent_turns=10, relevant_turns=0))
    wired.inference.script = [calls("lights")]
    with pytest.raises(RespondUnavailable):
        asyncio.run(respond(inbound()))
    assert wired.tools.called == []


def test_unreachable_tools_mean_none_offered_and_the_reply_goes_on(wired: Fakes) -> None:
    wired.tools.reachable = False
    wired.inference.script = [REPLY]
    assert asyncio.run(respond(inbound())).body == REPLY.text
    assert wired.inference.prompts[0].tools == ()
    assert wired.contexts[0].tools_reachable is False and wired.contexts[0].tool_instructions is None


def test_a_conversation_closing_between_is_asked_once_more(wired: Fakes) -> None:
    wired.conversations.closing = 1
    wired.inference.script = [REPLY]
    asyncio.run(respond(inbound()))
    assert [c[0] for c in wired.conversations.calls] == ["for_thread", "add_turn", "for_thread", "add_turn", "add_turn"]


def test_the_conversation_a_message_starts_records_its_channel_and_place(wired: Fakes) -> None:
    wired.inference.script = [REPLY]
    asyncio.run(respond(inbound()))
    assert wired.conversations.opened == {1: ("device", "kitchen")}


def test_closing_twice_is_unavailable(wired: Fakes, capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    wired.conversations.closing = 2
    with pytest.raises(RespondUnavailable):
        asyncio.run(respond(inbound()))
    assert [e["reason"] for e in events(capsys.readouterr().out, "respond.failed")] == ["closed_again"]


@pytest.mark.parametrize(("error", "raised", "reason"), [
    (InferenceRefused("no"), RespondRefused, "refused"),
    (InferenceUnavailable("no"), RespondUnavailable, "inference_unavailable"),
])
def test_a_failed_reply_keeps_the_person_turn(wired: Fakes, capsys: pytest.CaptureFixture[str], error: Exception,
                                              raised: type[Exception], reason: str) -> None:
    logs.setup()
    wired.inference.script = [error]
    with pytest.raises(raised):
        asyncio.run(respond(inbound()))
    assert turns(wired) == [("person", "hello", None)]
    assert [e["reason"] for e in events(capsys.readouterr().out, "respond.failed")] == [reason]


def test_an_unrecorded_reply_is_still_delivered(wired: Fakes, capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    wired.conversations.failing_ashley = True
    wired.inference.script = [REPLY]
    assert asyncio.run(respond(inbound())).body == REPLY.text
    assert len(events(capsys.readouterr().out, "respond.turn_unrecorded")) == 1


@pytest.mark.parametrize(("text", "thread"), [("", "t"), ("  ", "t"), ("hi", ""), ("hi", " ")])
def test_empty_text_or_thread_is_refused_before_anything(wired: Fakes, text: str, thread: str) -> None:
    with pytest.raises(ValueError):
        asyncio.run(respond(inbound(text, thread)))
    assert wired.conversations.calls == [] and wired.inference.prompts == []


def test_done_logs_counts_and_never_text(wired: Fakes, capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    wired.presence.answer = frozenset({ALANA.id})
    wired.tools.result = MARK
    wired.inference.script = [calls("lights", "lights"), Reply(spoken=MARK, text=MARK)]
    asyncio.run(respond(inbound(f"say {MARK}")))
    out = capsys.readouterr().out
    done = events(out, "respond.done")
    assert len(done) == 1
    assert {k: done[0][k] for k in ("kind", "medium", "tool_rounds", "tool_calls", "tools_required", "speaker")} == {
        "kind": "command", "medium": "text", "tool_rounds": "1", "tool_calls": "2", "tools_required": "0",
        "speaker": "known"}
    assert "conversation" in done[0] and "duration_ms" in done[0]
    assert (done[0]["standing_facts"], done[0]["recalled_facts"]) == ("unavailable", "unavailable")
    assert MARK not in out and "Alana" not in out


def test_offered_logs_the_tool_names_and_nothing_else(wired: Fakes, capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    wired.inference.script = [REPLY]
    asyncio.run(respond(inbound(f"say {MARK}")))
    out = capsys.readouterr().out
    (offered,) = events(out, "respond.offered")
    assert offered["tools"] == "lights" and "conversation" in offered
    assert MARK not in out


def test_done_counts_the_steps_asked_again_with_tools_required(wired: Fakes, capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    wired.inference.script = [Reply(answers=False, spoken="hold on", text="hold on"), calls("lights"), REPLY]
    asyncio.run(respond(inbound()))
    done = events(capsys.readouterr().out, "respond.done")
    assert (done[0]["tools_required"], done[0]["tool_calls"]) == ("1", "1")


def test_a_reply_after_tool_calls_is_validated_into_tool_calls_and_results(wired: Fakes) -> None:
    wired.inference.script = [calls("lights"), REPLY]
    asyncio.run(respond(inbound()))
    entries = wired.inference.prompts[1].messages
    assert isinstance(entries[1], ToolCalls) and isinstance(entries[2], ToolResults)
