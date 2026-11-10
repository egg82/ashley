"""A reply with nothing for the turn's medium is asked again once, then replaced by the fixed line, at the tool loop:
`answer`, `resume` and `resumed`, for each medium."""

import asyncio
import time

import pytest
from ashley.channels import tool_loop
from ashley.channels.model import Medium
from ashley.channels.tool_loop import Answer, Held, Progress
from ashley.inference.model import Message, ToolCalls, ToolResult, ToolResults
from ashley.inference.reply import Reply
from contract.conversations_support import events
from answer_dropped_blind_support import (CHECKING, EMPTIES, EMPTY, GOOD, HISTORY, LINE, SAID_ONLY, SENTINEL, SWITCH,
                                          SYSTEM, WRITTEN_ONLY, Model, Switch, delivered, limits, switch_on)

MEDIA: list[Medium] = ["text", "spoken"]


def answered(medium: Medium, *script: ToolCalls | Reply, rounds: int = 6, tools: bool = False, model: Model, source: Switch | None = None,
             ) -> Answer:
    model.play(*script)
    out = asyncio.run(tool_loop.answer("chat", SYSTEM, HISTORY, (SWITCH,) if tools else (), limits(rounds), 7,
                                       source=source or Switch(), medium=medium))
    assert isinstance(out, Answer)
    return out


@pytest.mark.parametrize("medium", MEDIA)
@pytest.mark.parametrize("empty", EMPTIES)
def test_an_empty_reply_is_asked_again_and_the_second_is_the_answer(loop: Model, capsys: pytest.CaptureFixture[str],
                                                                    medium: Medium, empty: Reply) -> None:
    out = answered(medium, empty, GOOD, model=loop)
    assert delivered(out.reply, medium) == delivered(GOOD, medium)
    assert loop.steps == 2
    assert len(events(capsys.readouterr().out, "respond.reply_empty")) == 1


@pytest.mark.parametrize("medium", MEDIA)
@pytest.mark.parametrize("empty", EMPTIES)
def test_two_empty_replies_end_in_the_fixed_line_after_exactly_two_steps(loop: Model, medium: Medium, empty: Reply) -> None:
    out = answered(medium, empty, empty, model=loop)
    assert delivered(out.reply, medium) == LINE
    assert loop.steps == 2


@pytest.mark.parametrize("medium", MEDIA)
def test_the_second_reply_is_not_asked_a_third_time_when_it_is_empty_and_the_first_was_not(loop: Model, medium: Medium) -> None:
    """A good reply is never touched, however many steps came before it."""
    out = answered(medium, GOOD, model=loop)
    assert out.reply == GOOD and loop.steps == 1


def test_a_reply_with_something_to_deliver_logs_no_empty_event(loop: Model, capsys: pytest.CaptureFixture[str]) -> None:
    answered("text", GOOD, model=loop)
    assert events(capsys.readouterr().out, "respond.reply_empty") == []


@pytest.mark.parametrize(("medium", "reply"), [("spoken", WRITTEN_ONLY), ("text", SAID_ONLY)])
def test_only_the_mediums_own_field_counts(loop: Model, medium: Medium, reply: Reply) -> None:
    """Text in the field the medium does not deliver is nothing to deliver: asked again."""
    out = answered(medium, reply, GOOD, model=loop)
    assert delivered(out.reply, medium) == delivered(GOOD, medium)
    assert loop.steps == 2


@pytest.mark.parametrize(("medium", "reply"), [("text", WRITTEN_ONLY), ("spoken", SAID_ONLY)])
def test_the_mediums_own_field_alone_is_enough(loop: Model, medium: Medium, reply: Reply) -> None:
    out = answered(medium, reply, model=loop)
    assert out.reply == reply and loop.steps == 1


@pytest.mark.parametrize(("medium", "reply"), [("spoken", WRITTEN_ONLY), ("text", SAID_ONLY)])
def test_nothing_in_the_mediums_field_twice_is_the_line_in_that_field(loop: Model, medium: Medium, reply: Reply) -> None:
    out = answered(medium, reply, reply, model=loop)
    assert delivered(out.reply, medium) == LINE


def test_the_medium_defaults_to_text(loop: Model) -> None:
    loop.play(SAID_ONLY, GOOD)
    out = asyncio.run(tool_loop.answer("chat", SYSTEM, HISTORY, (), limits(), 7, source=Switch()))
    assert isinstance(out, Answer) and out.reply == GOOD and loop.steps == 2


@pytest.mark.parametrize("medium", MEDIA)
def test_a_reply_that_is_not_worth_saying_is_not_asked_again(loop: Model, medium: Medium) -> None:
    quiet = Reply(worth_saying=False, spoken="", text="")
    out = answered(medium, quiet, model=loop)
    assert out.reply == quiet and loop.steps == 1


@pytest.mark.parametrize("medium", MEDIA)
def test_the_second_ask_carries_a_note_the_first_did_not(loop: Model, medium: Medium) -> None:
    answered(medium, EMPTY, GOOD, model=loop)
    first, second = loop.prompts
    assert len(second.messages) > len(first.messages)
    assert second.messages[: len(first.messages)] == first.messages


@pytest.mark.parametrize("medium", MEDIA)
def test_an_empty_closing_step_after_the_last_round_is_asked_again_under_tool_choice_none(loop: Model, medium: Medium) -> None:
    source = Switch()
    out = answered(medium, switch_on(), EMPTY, GOOD, rounds=1, tools=True, model=loop, source=source)
    assert delivered(out.reply, medium) == delivered(GOOD, medium)
    assert len(source.ran) == 1 and loop.steps == 3
    assert loop.choices[-2:] == ["none", "none"]


@pytest.mark.parametrize("medium", MEDIA)
def test_after_six_rounds_an_empty_closing_step_twice_is_the_line_and_no_tool_runs_again(loop: Model, medium: Medium) -> None:
    source = Switch()
    script = [switch_on(f"c{i}") for i in range(6)]
    out = answered(medium, *script, EMPTY, EMPTY, rounds=6, tools=True, model=loop, source=source)
    assert delivered(out.reply, medium) == LINE
    assert len(source.ran) == 6 and loop.steps == 8
    assert loop.choices[-2:] == ["none", "none"]


def test_the_empty_event_carries_ids_and_a_count_and_no_content(loop: Model, capsys: pytest.CaptureFixture[str]) -> None:
    leaky = Reply(spoken="", text="", offer=SENTINEL)
    answered("text", leaky, leaky, model=loop)
    out = capsys.readouterr().out
    assert len(events(out, "respond.reply_empty")) >= 1
    assert SENTINEL not in out


# held, then resumed (`resume`)

def _held(loop: Model, source: Switch) -> Held:
    loop.play(CHECKING)
    out = asyncio.run(tool_loop.answer("chat", SYSTEM, HISTORY, (SWITCH,), limits(), 7, True, source))
    assert isinstance(out, Held)
    return out


def _resume(held: Held, loop: Model, source: Switch, medium: Medium, *script: ToolCalls | Reply) -> Answer:
    loop.play(*script)
    return asyncio.run(tool_loop.resume(held, "chat", SYSTEM, (SWITCH,), limits(), 7, source, medium=medium))


@pytest.mark.parametrize("medium", MEDIA)
def test_a_resumed_held_turn_whose_next_reply_is_empty_is_asked_again(loop: Model, medium: Medium) -> None:
    source = Switch()
    held = _held(loop, source)
    out = _resume(held, loop, source, medium, switch_on(), EMPTY, GOOD)
    assert delivered(out.reply, medium) == delivered(GOOD, medium)


@pytest.mark.parametrize("medium", MEDIA)
def test_a_resumed_held_turn_whose_replies_stay_empty_ends_in_the_line(loop: Model, medium: Medium) -> None:
    source = Switch()
    held = _held(loop, source)
    steps_before = loop.steps
    out = _resume(held, loop, source, medium, EMPTY, EMPTY)
    assert delivered(out.reply, medium) == LINE
    assert loop.steps - steps_before == 2


def test_a_resumed_held_turn_reads_the_medium_it_is_given(loop: Model) -> None:
    source = Switch()
    held = _held(loop, source)
    out = _resume(held, loop, source, "spoken", WRITTEN_ONLY, SAID_ONLY)
    assert out.reply == SAID_ONLY


# resumed by another runner (`resumed`)

ENTRIES = (Message("person", "turn on the lamp"), switch_on(), ToolResults((ToolResult("c1", '{"on": true}'),)))


def _resumed(loop: Model, medium: Medium, progress: Progress, *script: ToolCalls | Reply, rounds: int = 6,
             source: Switch | None = None) -> Answer:
    loop.play(*script)
    return asyncio.run(tool_loop.resumed(progress, "chat", SYSTEM, (SWITCH,), limits(rounds), 7, source or Switch(), False,
                                         time.perf_counter(), medium=medium))


@pytest.mark.parametrize("medium", MEDIA)
def test_a_turn_resumed_by_another_runner_asks_an_empty_reply_again(loop: Model, medium: Medium) -> None:
    out = _resumed(loop, medium, Progress(ENTRIES, 1, 1), EMPTY, GOOD)
    assert delivered(out.reply, medium) == delivered(GOOD, medium) and loop.steps == 2


@pytest.mark.parametrize("medium", MEDIA)
def test_a_turn_resumed_by_another_runner_ends_in_the_line_after_two_empties(loop: Model, medium: Medium) -> None:
    out = _resumed(loop, medium, Progress(ENTRIES, 1, 1), EMPTY, EMPTY)
    assert delivered(out.reply, medium) == LINE and loop.steps == 2


@pytest.mark.parametrize("medium", MEDIA)
def test_a_round_in_flight_finishes_and_the_next_empty_reply_is_still_asked_again(loop: Model, medium: Medium) -> None:
    source = Switch()
    entries = (Message("person", "turn on the lamp"),)
    progress = Progress(entries, 0, 1, asked=switch_on())
    out = _resumed(loop, medium, progress, EMPTY, EMPTY, source=source)
    assert delivered(out.reply, medium) == LINE
    assert len(source.ran) == 1 and loop.steps == 2


# a turn resumed already at its last tool round

@pytest.mark.parametrize("medium", MEDIA)
def test_a_turn_resumed_at_its_last_round_answers_at_the_closing_step(loop: Model, medium: Medium) -> None:
    """`Progress.rounds` equal to `max_tool_rounds`: no tool may run, the next step is the closing one under tool
    choice none, and it answers."""
    source = Switch()
    out = _resumed(loop, medium, Progress(ENTRIES, 1, 1), GOOD, rounds=1, source=source)
    assert delivered(out.reply, medium) == delivered(GOOD, medium)
    assert source.ran == [] and loop.choices == ["none"]


@pytest.mark.parametrize("medium", MEDIA)
def test_a_turn_resumed_at_its_last_round_whose_closing_step_is_empty_ends_in_the_line(loop: Model, medium: Medium) -> None:
    out = _resumed(loop, medium, Progress(ENTRIES, 1, 1), EMPTY, EMPTY, rounds=1)
    assert delivered(out.reply, medium) == LINE
    assert loop.choices == ["none", "none"]


@pytest.mark.parametrize("medium", MEDIA)
def test_a_round_in_flight_as_the_last_one_finishes_and_then_the_closing_step_answers(loop: Model, medium: Medium) -> None:
    source = Switch()
    progress = Progress((Message("person", "turn on the lamp"),), 0, 1, asked=switch_on())
    out = _resumed(loop, medium, progress, GOOD, rounds=1, source=source)
    assert delivered(out.reply, medium) == delivered(GOOD, medium)
    assert len(source.ran) == 1 and loop.choices == ["none"]




@pytest.mark.parametrize(("closing", "medium", "answer"), [([WRITTEN_ONLY, SAID_ONLY], "spoken", SAID_ONLY),
                                                           ([SAID_ONLY, WRITTEN_ONLY], "text", WRITTEN_ONLY)])
def test_a_turn_resumed_by_another_runner_judges_its_replies_by_its_medium(
        loop: Model, closing: list[Reply], medium: Medium, answer: Reply) -> None:
    out = _resumed(loop, medium, Progress(ENTRIES, 1, 1), *closing)
    assert out.reply == answer and loop.steps == 2
