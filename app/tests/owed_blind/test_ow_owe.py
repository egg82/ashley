"""What `respond` keeps of `Reply.owed`: only for a known speaker and a key in that turn's `Catalogue.unreachable`,
stored once through `Errands.owe` keyed by the person turn; anything else is dropped and counted `owed_dropped`."""

import asyncio
from dataclasses import replace

import pytest
from ashley.channels import turn_tools
from ashley.channels.respond import respond
from ashley.inference.model import ToolCall, ToolCalls
from ashley.tools.tools import Tools
from contract.conversations_support import events
from owed_blind_support import (ALANA, HOME, HOUSE, MARK, NOTHING_OWED, SAM, SEARCH, World, alana, done_lines, dropped_of,
                                inbound, owed_of, reply, speak)


def test_a_kept_owed_stores_one_errand_for_the_person_turn(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    world.tools.unreachable = (HOUSE,)
    world.say(reply(HOUSE))
    speak(alana())
    assert world.errands.owed == [(HOME.id, ALANA.id, world.conversation_id(), world.person_turn_id(), HOUSE)]
    (line,) = done_lines(capsys)
    assert (owed_of(line), dropped_of(line)) == (HOUSE, 0)


def test_the_source_is_the_key_the_model_named_when_several_are_out(world: World) -> None:
    world.tools.unreachable = (SEARCH, HOUSE)
    world.say(reply(HOUSE))
    speak(alana())
    assert [o[4] for o in world.errands.owed] == [HOUSE]


@pytest.mark.parametrize("medium", ["text", "spoken"])
def test_the_reply_still_goes_out_when_an_errand_is_stored(world: World, medium: str) -> None:
    world.tools.unreachable = (HOUSE,)
    world.say(reply(HOUSE, text="I can't reach the house now."))
    out = speak(alana(medium=medium))
    assert out.body == "I can't reach the house now."


def test_a_key_that_is_not_unreachable_is_dropped_and_counted(world: World,
                                                              capsys: pytest.CaptureFixture[str]) -> None:
    world.tools.unreachable = (SEARCH,)
    world.say(reply(HOUSE))
    speak(alana())
    assert world.errands.owed == []
    (line,) = done_lines(capsys)
    assert (owed_of(line), dropped_of(line)) == (NOTHING_OWED, 1)


def test_an_owed_while_every_source_answers_is_dropped(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    world.tools.unreachable = ()
    world.say(reply(HOUSE))
    speak(alana())
    assert world.errands.owed == []
    (line,) = done_lines(capsys)
    assert (owed_of(line), dropped_of(line)) == (NOTHING_OWED, 1)


def test_an_unknown_speaker_owes_nothing_and_the_owed_is_counted_dropped(
        world: World, capsys: pytest.CaptureFixture[str]) -> None:
    world.tools.unreachable = (HOUSE,)
    world.say(reply(HOUSE))
    speak(inbound())
    assert world.errands.owed == []
    (line,) = done_lines(capsys)
    assert (owed_of(line), dropped_of(line)) == (NOTHING_OWED, 1)


def test_a_speaker_known_from_who_is_home_owes(world: World) -> None:
    world.fakes.presence.answer = frozenset({SAM.id})
    world.tools.unreachable = (HOUSE,)
    world.say(reply(HOUSE))
    speak(inbound())
    assert [(o[1], o[4]) for o in world.errands.owed] == [(SAM.id, HOUSE)]


def test_no_catalogue_at_all_means_nothing_is_owed(world: World, capsys: pytest.CaptureFixture[str],
                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    def whole_source(*_args: object, **_kw: object) -> Tools:
        return world.tools

    monkeypatch.setattr(turn_tools, "for_turn", whole_source)
    world.tools.reachable = False
    world.say(reply(HOUSE))
    speak(alana())
    assert world.errands.owed == []
    (line,) = done_lines(capsys)
    assert (owed_of(line), dropped_of(line)) == (NOTHING_OWED, 1)


def test_no_owed_stores_nothing_and_counts_no_drop_even_when_a_source_is_out(
        world: World, capsys: pytest.CaptureFixture[str]) -> None:
    world.tools.unreachable = (HOUSE,)
    world.say(reply(None))
    speak(alana())
    assert world.errands.owed == []
    (line,) = done_lines(capsys)
    assert (owed_of(line), dropped_of(line)) == (NOTHING_OWED, 0)


def test_a_turn_with_tool_rounds_owes_at_most_once(world: World) -> None:
    world.tools.unreachable = (HOUSE,)
    calls = ToolCalls((ToolCall("c0", "lights", {}),))
    world.say(calls, calls, reply(HOUSE))
    speak(alana())
    assert len(world.errands.owed) == 1


def test_each_person_turn_owes_for_itself(world: World) -> None:
    world.tools.unreachable = (HOUSE,)
    world.say(reply(HOUSE), reply(HOUSE))
    speak(alana(text="add milk"))
    speak(alana(text="add eggs"))
    turn_ids = [o[3] for o in world.errands.owed]
    assert len(turn_ids) == 2 and len(set(turn_ids)) == 2


def test_the_log_carries_the_source_key_but_never_the_words(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    world.tools.unreachable = (HOUSE,)
    world.say(reply(HOUSE, text=f"cannot {MARK}"))
    asyncio.run(respond(replace(alana(), text=f"add {MARK}")))
    out = capsys.readouterr().out
    assert events(out, "respond.done") and MARK not in out


def test_a_store_that_is_down_does_not_fail_the_turn(world: World) -> None:
    world.tools.unreachable = (HOUSE,)
    world.errands.fail_owe = True
    world.say(reply(HOUSE, text="I can't reach the house now."))
    assert speak(alana()).body == "I can't reach the house now."


def test_ow_the_source_stored_is_whichever_key_is_out(world: World) -> None:
    world.tools.unreachable = (SEARCH,)
    world.say(reply(SEARCH))
    speak(alana())
    assert [o[4] for o in world.errands.owed] == [SEARCH]
