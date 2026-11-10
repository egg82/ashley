"""`Errands.told` on the ids the prompt carried, once her turn is stored; a failure there is logged
`respond.told_unrecorded` and costs only saying it again."""

import asyncio
from dataclasses import replace

import pytest
from ashley.channels.respond import RespondUnavailable, respond
from ashley.inference.inference import InferenceUnavailable
from contract.conversations_support import events
from later_support import until
from owed_blind_support import (MARK, TELL_MAX, World, alana, done, done_lines, held_aside, inbound, prompt_text, reply,
                                speak, told_of)


def test_the_ids_that_were_shown_are_told(world: World) -> None:
    world.errands.waiting = [done(7, "a"), done(9, "b")]
    world.say(reply())
    speak(alana())
    assert len(world.errands.told_calls) == 1
    assert sorted(world.errands.told_ids) == [7, 9]


def test_only_those_shown_under_the_cap_are_told(world: World) -> None:
    world.errands.waiting = [done(i, f"r{i}") for i in range(1, TELL_MAX + 4)]
    world.say(reply())
    speak(alana())
    assert sorted(world.errands.told_ids) == list(range(1, TELL_MAX + 1))


def test_told_runs_after_her_turn_is_stored_and_not_before(world: World) -> None:
    world.errands.waiting = [done(1, "a")]
    world.say(reply())
    speak(alana())
    trace = world.errands.trace
    assert "stored" in trace and "told" in trace
    assert trace.index("untold") < trace.index("stored") < trace.index("told")


def test_nothing_untold_tells_nothing(world: World) -> None:
    world.say(reply())
    speak(alana())
    assert world.errands.told_ids == []


def test_an_unknown_speaker_tells_nothing(world: World) -> None:
    world.errands.waiting = [done(1, "a")]
    world.say(reply())
    speak(inbound())
    assert world.errands.told_calls == [] and world.errands.waiting != []


def test_a_turn_that_fails_before_her_turn_is_stored_tells_nothing(world: World) -> None:
    world.errands.waiting = [done(1, "a")]
    world.say(InferenceUnavailable("down"))
    with pytest.raises(RespondUnavailable):
        speak(alana())
    assert world.errands.told_ids == []


def test_said_once_is_not_said_again_on_the_next_turn(world: World) -> None:
    world.errands.waiting = [done(1, "result-said-once")]
    world.say(reply(), reply())
    speak(alana(text="first"))
    speak(alana(text="second"))
    first, second = world.fakes.inference.prompts
    assert "result-said-once" in prompt_text(first) and "result-said-once" not in prompt_text(second)


def test_a_failed_told_is_logged_and_the_turn_is_still_answered_and_stored(
        world: World, capsys: pytest.CaptureFixture[str]) -> None:
    world.errands.waiting = [done(1, "a")]
    world.errands.fail_told = True
    world.say(reply(text="All set."))
    out = speak(alana())
    assert out.body == "All set."
    lines = capsys.readouterr().out
    assert len(events(lines, "respond.told_unrecorded")) == 1
    assert len(events(lines, "respond.done")) == 1
    conv = next(iter(world.fakes.conversations.convs.values()))
    assert [t.author for t in conv.turns] == ["person", "ashley"]


def test_a_successful_told_logs_no_told_unrecorded(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    world.errands.waiting = [done(1, "a")]
    world.say(reply())
    speak(alana())
    assert events(capsys.readouterr().out, "respond.told_unrecorded") == []


def test_a_held_reply_tells_after_the_answer_is_stored_not_the_held_line(
        world: World, capsys: pytest.CaptureFixture[str]) -> None:
    world.errands.waiting = [done(4, "held-turn-result")]
    world.say(held_aside(), reply(text="The real answer."))

    async def scenario() -> None:
        out = await respond(replace(alana(), later=True, later_by="turn"))
        assert out.follows
        assert world.errands.told_calls == []
        await until(lambda: world.errands.told_calls)

    asyncio.run(scenario())
    trace = world.errands.trace
    assert trace.count("stored") == 2 and trace.count("told") == 1
    assert trace.index("told") > len(trace) - 1 - trace[::-1].index("stored")
    assert world.errands.told_ids == [4]
    (line,) = done_lines(capsys)
    assert told_of(line) == (4,)


def test_the_result_text_is_not_logged_by_a_failed_told(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    world.errands.waiting = [done(1, f"did {MARK}")]
    world.errands.fail_told = True
    world.say(reply())
    speak(alana())
    assert MARK not in capsys.readouterr().out
