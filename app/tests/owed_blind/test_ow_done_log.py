"""`respond.done` gains `owed` (the source key kept, or none), `owed_dropped` and `told` (the errand ids)."""

import pytest
from owed_blind_support import HOUSE, NOTHING_OWED, World, alana, done, done_lines, dropped_of, inbound, owed_of, reply, \
    speak, told_of


def test_done_names_the_errand_ids_told_in_the_order_shown(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    world.errands.waiting = [done(5, "a"), done(3, "b")]
    world.say(reply())
    speak(alana())
    (line,) = done_lines(capsys)
    assert told_of(line) == (5, 3)


def test_done_has_an_empty_told_when_nothing_was_told(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    world.say(reply())
    speak(alana())
    (line,) = done_lines(capsys)
    assert "told" in line and told_of(line) == ()


def test_an_unknown_speaker_logs_no_told(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    world.errands.waiting = [done(1, "a")]
    world.say(reply())
    speak(inbound())
    (line,) = done_lines(capsys)
    assert told_of(line) == ()


def test_done_carries_owed_and_told_together(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    world.tools.unreachable = (HOUSE,)
    world.errands.waiting = [done(2, "a")]
    world.say(reply(HOUSE))
    speak(alana())
    (line,) = done_lines(capsys)
    assert (owed_of(line), dropped_of(line), told_of(line)) == (HOUSE, 0, (2,))


def test_done_says_none_owed_and_zero_dropped_for_an_ordinary_turn(world: World,
                                                                    capsys: pytest.CaptureFixture[str]) -> None:
    world.say(reply())
    speak(alana())
    (line,) = done_lines(capsys)
    assert (owed_of(line), dropped_of(line)) == (NOTHING_OWED, 0)
