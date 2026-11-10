"""What respond reads and shows: for a known speaker `Errands.untold` (at most `tell_max`, filtered for the hearer),
each result a line under `# While they were away`; an unknown speaker carries none."""

import pytest
from ashley.channels.model import Inbound
from ashley.inference.model import ToolCall, ToolCalls
from owed_blind_support import (ALANA, HEADING, MARK, SAM, TELL_MAX, World, alana, done, inbound, owner_alone,
                                prompt_text, reply, speak)


def lines_after_heading(text: str) -> list[str]:
    rows = text.splitlines()
    assert HEADING in rows, "the prompt has the heading as a line of its own"
    return rows[rows.index(HEADING) + 1:]


def test_a_known_speaker_reads_untold_for_themselves_with_the_cap(world: World) -> None:
    world.say(reply())
    speak(alana())
    assert world.errands.untold_calls == [(ALANA.id, TELL_MAX, False)]


def test_a_speaker_known_from_who_is_home_is_the_hearer(world: World) -> None:
    world.fakes.presence.answer = frozenset({SAM.id})
    world.say(reply())
    speak(inbound())
    assert [(c[0], c[1]) for c in world.errands.untold_calls] == [(SAM.id, TELL_MAX)]


def test_on_a_channel_only_they_hear_the_hearer_is_alone(world: World) -> None:
    world.say(reply())
    speak(owner_alone())
    assert world.errands.untold_calls == [(ALANA.id, TELL_MAX, True)]


def test_on_a_channel_others_hear_the_hearer_is_not_alone(world: World) -> None:
    world.say(reply())
    speak(alana())
    assert world.errands.untold_calls[0][2] is False


def test_it_is_read_once_per_turn_however_many_steps(world: World) -> None:
    calls = ToolCalls((ToolCall("c0", "lights", {}),))
    world.say(calls, calls, reply())
    speak(alana())
    assert len(world.errands.untold_calls) == 1


def test_each_result_is_a_line_under_the_heading(world: World) -> None:
    world.errands.waiting = [done(1, "I put cat litter on the list."), done(2, "I set the reminder for six.")]
    world.say(reply())
    speak(alana())
    after = lines_after_heading(prompt_text(world.fakes.inference.prompts[0]))
    assert any("cat litter" in line for line in after)
    assert any("reminder for six" in line for line in after)
    assert not any("cat litter" in line and "reminder for six" in line for line in after)


def test_the_results_come_oldest_first_as_the_store_gave_them(world: World) -> None:
    world.errands.waiting = [done(1, "first-result-aaa"), done(2, "second-result-bbb")]
    world.say(reply())
    speak(alana())
    text = prompt_text(world.fakes.inference.prompts[0])
    assert text.index("first-result-aaa") < text.index("second-result-bbb")


def test_no_untold_means_no_heading(world: World) -> None:
    world.say(reply())
    speak(alana())
    assert HEADING not in prompt_text(world.fakes.inference.prompts[0])


def test_at_most_tell_max_results_reach_the_prompt(world: World) -> None:
    world.errands.waiting = [done(i, f"result-number-{i:03d}") for i in range(1, TELL_MAX + 4)]
    world.say(reply())
    speak(alana())
    text = prompt_text(world.fakes.inference.prompts[0])
    shown = [i for i in range(1, TELL_MAX + 4) if f"result-number-{i:03d}" in text]
    assert shown == list(range(1, TELL_MAX + 1))


def test_every_step_of_the_turn_carries_them(world: World) -> None:
    world.errands.waiting = [done(1, "result-in-every-step")]
    world.say(ToolCalls((ToolCall("c0", "lights", {}),)), reply())
    speak(alana())
    prompts = world.fakes.inference.prompts
    assert len(prompts) == 2 and all("result-in-every-step" in prompt_text(p) for p in prompts)


@pytest.mark.parametrize("message", [inbound(), inbound(shared=False)])
def test_an_unknown_speaker_carries_none_and_the_store_is_not_read(world: World, message: Inbound) -> None:
    world.errands.waiting = [done(1, "result-for-nobody")]
    world.say(reply())
    speak(message)
    assert world.errands.untold_calls == []
    text = prompt_text(world.fakes.inference.prompts[0])
    assert HEADING not in text and "result-for-nobody" not in text


def test_a_store_that_is_down_costs_the_section_and_not_the_reply(world: World) -> None:
    world.errands.fail_untold = True
    world.say(reply(text="Fine."))
    assert speak(alana()).body == "Fine."
    assert HEADING not in prompt_text(world.fakes.inference.prompts[0])


def test_results_are_never_logged(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    world.errands.waiting = [done(1, f"I did {MARK}")]
    world.say(reply())
    speak(alana())
    assert MARK not in capsys.readouterr().out
