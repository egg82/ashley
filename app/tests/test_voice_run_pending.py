"""A wake whose reply is pending (her answer to come through the outbox, from the runner that finishes her turn): the
run ends after the intent with nothing to play, no clip stored and outcome `pending`."""

from collections.abc import Generator

import pytest
from aioesphomeapi.model import VoiceAssistantEventType as Event
from ashley import logs, services
from ashley.channels.voice.clips import Clips
from ashley.inference.inference import Inference
from contract.conversations_support import db_url as db_url, events, household
from contract.conversations_support import migrated_template as migrated_template, scalar
from test_voice_run import ANSWERED, carry
from voice_support import FakeSpeech, FakeTurnLoop, satellite_row

E = Event


@pytest.fixture(autouse=True)
def speech_unwired() -> Generator[None]:
    yield
    services.unregister(Inference)
    services.unregister(Clips)


def test_a_pending_reply_ends_the_run_with_nothing_played(db_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    satellite = satellite_row(db_url, household(db_url), room_speaker="media_player.office")
    link = carry(db_url, satellite, FakeSpeech(), FakeTurnLoop(body="", follows=True))
    assert link.kinds() == [*ANSWERED, E.VOICE_ASSISTANT_RUN_END]
    assert scalar(db_url, "SELECT count(*) FROM voice_clips") == 0
    assert [e["outcome"] for e in events(capsys.readouterr().out, "voice.run")] == ["pending"]
