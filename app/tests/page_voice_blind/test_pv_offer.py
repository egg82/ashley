"""Contract 1-3 and 7, blind: the tag and the offer. A typed message never offers her voice; a tagged one on the web chat
or the kiosk does, in one line of `# Now`; the line is for a known speaker or an unknown one; the medium stays the
channel's and her phone is not offered on it."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from ashley.channels import aloud, to_phone
from ashley.channels.model import Inbound
from ashley.persona import facts, persona
from ashley.persona.facts import ALOUD, ALOUD_UNKNOWN, PHONE
from pv_support import aloud_of, chat_inbound_for, hers, kiosk_inbound_for, real_prompt as real_prompt
from pv_support import run_turn, speak, system_text, voice_aloud_lines
from respond_support import ALANA, HOME, Fakes, inbound

NOW = datetime(2026, 11, 8, 9, 30, tzinfo=UTC)
KNOWN = ALOUD.format(name=ALANA.name)


def test_c01_a_typed_message_is_not_tagged_and_does_not_offer() -> None:
    for inbound in (chat_inbound_for(aloud=False), kiosk_inbound_for(aloud=False)):
        assert aloud_of(inbound) is False and aloud.offered(inbound) is False


def test_c01_a_message_that_says_it_was_aloud_in_words_is_not_tagged() -> None:
    inbound = chat_inbound_for("I said this aloud, on a page that can play your voice", aloud=False)
    assert aloud.offered(inbound) is False


def test_c01_a_typed_message_prompts_without_the_line(real_prompt: Fakes) -> None:
    run_turn(real_prompt, chat_inbound_for(aloud=False), [speak("Dry.", "Dry.", aloud=False)])
    text = system_text(real_prompt)
    assert "# Now" in text, "control: the facts section is in the prompt this reads"
    assert KNOWN not in text and ALOUD_UNKNOWN not in text
    assert real_prompt.contexts[0].aloud is False


def test_c02_a_tagged_chat_message_offers_with_the_speakers_name(real_prompt: Fakes) -> None:
    inbound = chat_inbound_for(aloud=True)
    assert aloud.offered(inbound) is True
    run_turn(real_prompt, inbound, [speak("Dry.", "Dry.", aloud=False)])
    text = system_text(real_prompt)
    assert KNOWN in text and ALOUD_UNKNOWN not in text
    assert real_prompt.contexts[0].aloud is True


def test_c02_a_tagged_kiosk_message_offers_without_a_name(real_prompt: Fakes) -> None:
    inbound = kiosk_inbound_for(aloud=True)
    assert aloud.offered(inbound) is True
    run_turn(real_prompt, inbound, [speak("Dry.", "Dry.", aloud=False)])
    text = system_text(real_prompt)
    assert ALOUD_UNKNOWN in text and "said this aloud" not in text.replace(ALOUD_UNKNOWN, "")
    assert real_prompt.contexts[0].aloud is True


def test_c02_the_two_lines_say_the_same_thing_with_and_without_a_name() -> None:
    assert "{name}" in ALOUD and "{name}" not in ALOUD_UNKNOWN
    for line in (ALOUD, ALOUD_UNKNOWN):
        assert "`aloud`" in line and "`spoken`" in line and "`text`" in line


def context(**changes: object) -> persona.Context:
    base = persona.Context(now=NOW, household=HOME, speaker=ALANA, home=None, place=None, tool_instructions=None,
                           tools_reachable=True)
    return replace(base, **changes)


def test_c02_the_facts_carry_the_line_only_when_offered() -> None:
    assert context().aloud is False
    plain = facts.facts(NOW, HOME, ALANA, None, None)
    offered = facts.facts(NOW, HOME, ALANA, None, None, aloud=True)
    assert KNOWN not in plain and KNOWN in offered
    assert [ln for ln in offered.splitlines() if ln != KNOWN] == plain.splitlines(), "the line is the only addition"


def test_c02_an_unknown_speaker_gets_the_unnamed_line() -> None:
    said = facts.facts(NOW, HOME, None, None, None, aloud=True)
    assert ALOUD_UNKNOWN in said and "{name}" not in said


def test_c02_the_aloud_line_follows_the_phone_line() -> None:
    said = facts.facts(NOW, HOME, ALANA, None, None, phone=True, aloud=True)
    assert said.index(PHONE.format(name="Alana")) < said.index(KNOWN)


def test_c02_the_real_persona_prompt_carries_the_line_from_the_context() -> None:
    plain = persona.system("chat", context())["default"]
    said = persona.system("chat", context(aloud=True))["default"]
    assert KNOWN not in plain.moment and KNOWN in said.moment and KNOWN not in said.stable


def test_c03_offered_and_not_chosen_stores_no_voice_and_logs_nothing(
        real_prompt: Fakes, capsys: pytest.CaptureFixture[str]) -> None:
    capsys.readouterr()
    run_turn(real_prompt, chat_inbound_for(aloud=True), [speak("Dry.", "Dry all day.", aloud=False)])
    [turn] = hers(real_prompt)
    assert (turn.text, turn.spoken) == ("Dry all day.", None)
    assert voice_aloud_lines(capsys.readouterr().out) == []


def test_c07_a_tagged_message_keeps_the_channels_medium_and_never_offers_the_phone(real_prompt: Fakes) -> None:
    for inbound in (chat_inbound_for(aloud=True), kiosk_inbound_for(aloud=True)):
        assert inbound.medium == "text"
        assert asyncio.run(to_phone.reachable(inbound, ALANA)) is None
    run_turn(real_prompt, chat_inbound_for(aloud=True), [speak("Dry.", "Dry.", aloud=False)])
    assert real_prompt.contexts[0].phone is False
    assert "send `text` to" not in system_text(real_prompt)


def test_c07_a_spoken_medium_message_is_never_offered_even_if_tagged() -> None:
    inbound: Inbound = replace(chat_inbound_for(aloud=True), medium="spoken")
    assert aloud.offered(inbound) is False


def test_c07_the_tag_defaults_off_on_an_inbound_built_by_hand() -> None:
    assert aloud_of(inbound()) is False
