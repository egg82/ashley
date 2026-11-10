"""Contract 1, 3, 4 and 5, blind: her decision. `aloud` is honoured only on an offer; her turn then stores `spoken` in
real spellings beside `text`, a held line and its answer each their own; `voice.aloud` is one line per reply that sets
the field and carries no words."""

import pytest
from ashley.channels import aloud
from ashley.inference.reply import Reply
from ashley import logs
from pv_support import chat_inbound_for, hers, kiosk_inbound_for, raw_lines, run_turn, speak
from pv_support import voice_aloud_lines
from pv_support import real_prompt as real_prompt
from respond_support import Fakes

MOWCHI = "Mowchi is asleep, so I will keep it down."


def test_c04_the_field_defaults_off_and_is_in_every_schema() -> None:
    assert Reply(spoken="a", text="a").aloud is False
    schema = Reply.model_json_schema()
    assert "aloud" in schema["required"] and "default" not in schema["properties"]["aloud"]


def test_c04_the_field_describes_its_shape_without_an_example_sentence() -> None:
    description = Reply.model_json_schema()["properties"]["aloud"]["description"]
    assert "`spoken`" in description and "`text`" in description and '"' not in description


def test_c04_offered_and_chosen_stores_her_spoken_in_real_spellings_beside_text(
        real_prompt: Fakes, capsys: pytest.CaptureFixture[str]) -> None:
    capsys.readouterr()
    run_turn(real_prompt, chat_inbound_for(), [speak(MOWCHI, "Mowchi is asleep.")])
    [turn] = hers(real_prompt)
    assert (turn.text, turn.spoken, turn.follows) == ("Mowchi is asleep.", MOWCHI, False)
    [line] = voice_aloud_lines(capsys.readouterr().out)
    assert line["outcome"] == "said" and line["conversation"] == "1"


def test_c04_the_kiosk_stores_it_the_same_way(real_prompt: Fakes) -> None:
    run_turn(real_prompt, kiosk_inbound_for(), [speak("It is dry.", "Dry.")])
    [turn] = hers(real_prompt)
    assert (turn.text, turn.spoken) == ("Dry.", "It is dry.")


def test_c04_the_line_carries_no_words(real_prompt: Fakes, capsys: pytest.CaptureFixture[str]) -> None:
    capsys.readouterr()
    run_turn(real_prompt, chat_inbound_for("zqASKED about the weather"), [speak("zqSPOKEN", "zqTEXT")])
    out = capsys.readouterr().out
    assert voice_aloud_lines(out), "control: the line was written"
    assert not [w for w in ("zqASKED", "zqSPOKEN", "zqTEXT") if w in raw_lines(out, "voice.aloud")]


def test_c01_a_typed_message_with_aloud_set_stores_no_voice_and_logs_not_offered(
        real_prompt: Fakes, capsys: pytest.CaptureFixture[str]) -> None:
    capsys.readouterr()
    run_turn(real_prompt, chat_inbound_for(aloud=False), [speak("Dry.", "Dry all day.")])
    [turn] = hers(real_prompt)
    assert (turn.text, turn.spoken) == ("Dry all day.", None)
    [line] = voice_aloud_lines(capsys.readouterr().out)
    assert line["outcome"] == "not_offered"


def test_c01_the_kiosk_typed_is_the_same(real_prompt: Fakes, capsys: pytest.CaptureFixture[str]) -> None:
    capsys.readouterr()
    run_turn(real_prompt, kiosk_inbound_for(aloud=False), [speak("Dry.", "Dry.")])
    assert [t.spoken for t in hers(real_prompt)] == [None]
    assert [x["outcome"] for x in voice_aloud_lines(capsys.readouterr().out)] == ["not_offered"]


def test_c05_a_held_line_stores_its_own_voice_and_the_answer_its_own(real_prompt: Fakes) -> None:
    held = speak("Checking now.", "Let me check.", answers=False)
    final = speak("It is dry all day.", "Dry all day.")
    run_turn(real_prompt, chat_inbound_for(), [held, final], stored=2)
    first, second = hers(real_prompt)
    assert (first.text, first.spoken, first.follows) == ("Let me check.", "Checking now.", True)
    assert (second.text, second.spoken, second.follows) == ("Dry all day.", "It is dry all day.", False)


def test_c05_a_held_line_that_stays_silent_does_not_silence_the_answer(real_prompt: Fakes) -> None:
    held = speak("Checking now.", "Let me check.", aloud=False, answers=False)
    final = speak("It is dry all day.", "Dry all day.")
    run_turn(real_prompt, chat_inbound_for(), [held, final], stored=2)
    assert [t.spoken for t in hers(real_prompt)] == [None, "It is dry all day."]


def test_c05_an_answer_that_stays_silent_after_a_voiced_held_line_stores_none(
        real_prompt: Fakes, capsys: pytest.CaptureFixture[str]) -> None:
    capsys.readouterr()
    held = speak("Checking now.", "Let me check.", answers=False)
    run_turn(real_prompt, chat_inbound_for(), [held, speak("Dry.", "Dry.", aloud=False)], stored=2)
    assert [t.spoken for t in hers(real_prompt)] == ["Checking now.", None]
    assert [x["outcome"] for x in voice_aloud_lines(capsys.readouterr().out)] == ["said"]


def test_c05_a_held_line_on_a_typed_turn_stores_no_voice(real_prompt: Fakes) -> None:
    held = speak("Checking now.", "Let me check.", answers=False)
    run_turn(real_prompt, chat_inbound_for(aloud=False), [held, speak("Dry.", "Dry.")], stored=2)
    assert [t.spoken for t in hers(real_prompt)] == [None, None]


def test_c05_each_reply_that_sets_the_field_logs_once(real_prompt: Fakes, capsys: pytest.CaptureFixture[str]) -> None:
    capsys.readouterr()
    held = speak("Checking now.", "Let me check.", answers=False)
    run_turn(real_prompt, chat_inbound_for(), [held, speak("Dry.", "Dry.")], stored=2)
    assert [x["outcome"] for x in voice_aloud_lines(capsys.readouterr().out)] == ["said", "said"]


def test_c04_spoken_returns_her_spoken_only_for_an_offer_that_she_took() -> None:
    tagged, typed = chat_inbound_for(aloud=True), chat_inbound_for(aloud=False)
    chosen, declined = speak("Hello there."), speak("Hello there.", aloud=False)
    assert aloud.spoken(chosen, tagged, 5) == "Hello there."
    assert aloud.spoken(declined, tagged, 5) is None
    assert aloud.spoken(chosen, typed, 5) is None
    assert aloud.spoken(declined, typed, 5) is None


def test_c01_spoken_logs_by_outcome_and_only_when_the_field_is_set(capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    capsys.readouterr()
    tagged, typed = chat_inbound_for(aloud=True), chat_inbound_for(aloud=False)
    aloud.spoken(speak("a", aloud=False), tagged, 5)
    aloud.spoken(speak("b"), tagged, 6)
    aloud.spoken(speak("c"), typed, 7)
    got = [(x["conversation"], x["outcome"]) for x in voice_aloud_lines(capsys.readouterr().out)]
    assert got == [("6", "said"), ("7", "not_offered")]
