"""Contract 1 and 3: a held line is one aside, the first of its round, said whole, never a later call's; the prompt
asks for an aside as a shape and gives no example sentence."""

from ashley.channels import aside
from ashley.channels.tool_loop import Held, answer
from ashley.inference.model import Entry, ToolCall, ToolCalls, ToolResult, ToolResults
from ashley.inference.reply import Reply
from bgb_support import (CONVERSATION, FINAL, HISTORY, LAST, READ, RUN, SYSTEM, TOOLS, Rig, Timed, brainstorm, drive, one,
                         round_of)
from contract.inference_support import settle


def calls(*asides: str | None) -> ToolCalls:
    return ToolCalls(tuple(ToolCall(f"c{i}", "t", {} if a is None else {aside.FIELD: a}) for i, a in enumerate(asides)))


def test_c1_two_calls_in_one_round_hold_the_first_ones_aside() -> None:
    assert aside.latest([calls("A", "B")]) == "A"


def test_c1_control_the_old_last_of_all_reading_is_not_the_contract() -> None:
    assert aside.latest([calls("A", "B")]) != "B"


def test_c1_an_earlier_round_does_not_beat_the_latest_round_that_has_one() -> None:
    entries: list[Entry] = [calls("C"), ToolResults((ToolResult("c0", "ok"),)), calls(None, "D")]
    assert aside.latest(entries) == "D"


def test_c1_the_first_non_blank_of_the_latest_round_with_an_aside() -> None:
    assert aside.latest([calls("C"), calls("  ", "D", "E")]) == "D"


def test_c1_a_latest_round_with_no_aside_falls_back_to_the_round_before() -> None:
    assert aside.latest([calls("C"), calls(None, "   ")]) == "C"


def test_c1_no_asides_is_none() -> None:
    assert aside.latest([]) is None
    assert aside.latest([calls(None, "")]) is None


def test_c1_the_aside_is_returned_stripped() -> None:
    assert aside.latest([calls("  Making the clip.  ")]) == "Making the clip."


def test_c1_a_held_line_after_a_multi_call_round_is_the_first_calls_aside_whole(rig: Rig) -> None:
    first, second = "Working out how the clip should sit.", "And what the last run gave."
    rig.model.script = [round_of(0, (READ, first), (LAST, second)), FINAL]
    got = settle(drive(rig, brainstorm(hold_after_s=60.0), seconds=35.0))
    assert got.held == [first]
    assert got.answer.reply == FINAL


def test_c1_the_held_reply_is_the_holding_form_of_that_aside(rig: Rig) -> None:
    rig.model.script = [round_of(0, (RUN, "Building the gate.")), FINAL]

    async def first_held() -> Held:
        got = await answer("brainstorm", SYSTEM, HISTORY, TOOLS, brainstorm(hold_after_s=5.0), CONVERSATION, hold=True,
                           source=Timed(rig.clock, 6.0), started=1000.0, clock=rig.clock)
        assert isinstance(got, Held)
        return got

    held = settle(first_held())
    assert held.by == "aside_budget" and held.reply == aside.holding("Building the gate.")
    assert held.reply == Reply(answers=False, spoken="Building the gate.", text="Building the gate.")


def test_c1_a_later_round_of_blank_then_d_holds_d_not_an_earlier_rounds_c(rig: Rig) -> None:
    rig.model.script = [one(0, READ, "Reading for C."), round_of(1, (READ, None), (LAST, "Then D.")), FINAL]
    got = settle(drive(rig, brainstorm(hold_after_s=60.0), seconds=35.0))
    assert got.held == ["Then D."]


def test_c3_the_aside_description_is_a_shape_with_no_example_sentence() -> None:
    text = aside.DESCRIPTION
    assert text.strip()
    for quote in ('"', "“", "”"):
        assert quote not in text
    assert "e.g." not in text and "for example" not in text.lower()


def test_c3_the_description_no_longer_asks_what_you_are_doing() -> None:
    assert "what you are doing" not in aside.DESCRIPTION


def test_c3_the_description_tells_each_aside_to_stand_alone_of_its_siblings() -> None:
    assert "only one" in aside.DESCRIPTION.lower()


def test_c3_every_offered_tool_carries_that_description() -> None:
    for spec in aside.offered(TOOLS):
        props = spec.parameters["properties"]
        assert isinstance(props, dict) and props[aside.FIELD]["description"] == aside.DESCRIPTION
