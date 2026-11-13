"""A voice reply can decline or offer: a satellite's wake may have been overheard (`Inbound.overhears`), so her reply's
`Reply.says` is honoured there. `none` plays nothing, stores no clip, does not continue the conversation and is stored
as her staying quiet; `reply` and `offer` are played. `voice.run` carries the choice. Elsewhere a person's turn is
always said. The field's schema holds for every provider's wire."""

import asyncio
import json
from collections.abc import Callable, Generator
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest
from aioesphomeapi.model import VoiceAssistantEventType as Event
from ashley import logs, services
from ashley.channels.respond import respond
from ashley.channels.voice.clips import Clips
from ashley.conversations.quiet import QUIET
from ashley.inference import anthropic_wire, openai_wire
from ashley.inference.inference import Inference
from ashley.inference.reply import Reply, Says
from ashley.persona import facts
from contract.conversations_support import db_url as db_url, events, household
from contract.conversations_support import migrated_template as migrated_template, scalar
from respond_support import HOME, Fakes, inbound, wired as wired
from test_voice_run import ANSWERED, carry
from voice_support import FakeSpeaker, FakeSpeech, FakeTurnLoop, satellite_row

E = Event
PLAYED = [*ANSWERED, E.VOICE_ASSISTANT_TTS_START, E.VOICE_ASSISTANT_TTS_END, E.VOICE_ASSISTANT_RUN_END]
SILENT = [*ANSWERED, E.VOICE_ASSISTANT_RUN_END]
VALUES: tuple[Says, ...] = ("reply", "offer", "none")


@pytest.fixture
def speech_unwired() -> Generator[None]:
    yield
    services.unregister(Inference)
    services.unregister(Clips)


@pytest.mark.parametrize("says", VALUES)
def test_the_run_plays_her_reply_unless_she_declined(db_url: str, speech_unwired: None, says: Says,
                                                     capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    loop = FakeTurnLoop(body="Want me to dim them?", says=says)
    link = carry(db_url, satellite_row(db_url, household(db_url)), FakeSpeech(), loop)
    assert loop.asked[0].overhears is True
    assert link.kinds() == (SILENT if says == "none" else PLAYED)
    assert link.data(E.VOICE_ASSISTANT_INTENT_END) == {"conversation_id": "41", "continue_conversation": "0"}
    assert scalar(db_url, "SELECT count(*) FROM voice_clips") == (0 if says == "none" else 1)
    [run] = events(capsys.readouterr().out, "voice.run")
    assert (run["says"], run["outcome"]) == (says, "silent" if says == "none" else "ok")
    assert "dim" not in str(run)


def test_a_declined_reply_is_not_played_on_the_room_speaker_either(db_url: str, speech_unwired: None) -> None:
    speaker = FakeSpeaker()
    satellite = satellite_row(db_url, household(db_url), room_speaker="media_player.office")
    link = carry(db_url, satellite, FakeSpeech(), FakeTurnLoop(says="none"), speaker)
    assert speaker.played == [] and link.kinds() == SILENT


def _stored(fakes: Fakes) -> str:
    return next(iter(fakes.conversations.convs.values())).turns[-1].text


@pytest.mark.parametrize("says", VALUES)
def test_an_overheard_turn_honours_her_choice_and_stores_a_decline_as_quiet(wired: Fakes, says: Says) -> None:
    wired.inference.script = [Reply(spoken="Shall I add milk?", text="Shall I add milk?", says=says)]
    out = asyncio.run(respond(replace(inbound(medium="spoken"), channel="voice", overhears=True)))
    assert out.says == says and wired.contexts[-1].overhears is True
    assert _stored(wired) == (QUIET if says == "none" else "Shall I add milk?")


@pytest.mark.parametrize("says", ("offer", "none"))
def test_a_turn_not_overheard_is_said_whatever_she_set(wired: Fakes, says: Says) -> None:
    wired.inference.script = [Reply(spoken="It is noon.", text="It is noon.", says=says)]
    out = asyncio.run(respond(inbound(medium="spoken")))
    assert out.says == "reply" and wired.contexts[-1].overhears is False
    assert _stored(wired) == "It is noon."


def test_the_prompt_offers_declining_only_on_an_overheard_turn() -> None:
    now = datetime(2026, 11, 13, 9, 0, tzinfo=UTC)
    assert facts.OVERHEARD in facts.facts(now, HOME, None, None, "office", overhears=True)
    assert "`says`" not in facts.facts(now, HOME, None, None, "office")
    assert '"' not in facts.OVERHEARD, "the shape is described, never a quoted sentence"


@pytest.mark.parametrize("build", (anthropic_wire.reply_schema, openai_wire.reply_schema),
                         ids=("anthropic", "openai-compatible"))
def test_the_field_is_a_required_enum_of_the_three_on_every_wire(build: Callable[[type[Reply]], object]) -> None:
    schema: Any = json.loads(json.dumps(build(Reply)))
    says = schema["properties"]["says"]
    assert says["enum"] == list(VALUES) and "says" in schema["required"] and "default" not in says
