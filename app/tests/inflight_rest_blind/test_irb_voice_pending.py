"""A voice reply with no words (pending: her answer comes through the outbox) is logged as `outcome=pending`, and a reply
with words is not."""

from collections.abc import Generator

import pytest
from ashley import logs, services
from ashley.channels.voice.clips import Clips
from ashley.inference.inference import Inference
from contract.conversations_support import db_url as db_url, events, household
from contract.conversations_support import migrated_template as migrated_template
from test_voice_run import carry
from voice_support import FakeSpeech, FakeTurnLoop, satellite_row


@pytest.fixture(autouse=True)
def speech_unwired() -> Generator[None]:
    yield
    services.unregister(Inference)
    services.unregister(Clips)


def outcomes(db_url: str, capsys: pytest.CaptureFixture[str], loop: FakeTurnLoop) -> list[object]:
    logs.setup()
    satellite = satellite_row(db_url, household(db_url), room_speaker="media_player.office")
    carry(db_url, satellite, FakeSpeech(), loop)
    return [e["outcome"] for e in events(capsys.readouterr().out, "voice.run")]


def test_a_reply_with_no_words_is_pending(db_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    assert outcomes(db_url, capsys, FakeTurnLoop(body="", follows=True)) == ["pending"]


def test_a_reply_with_words_is_not_pending(db_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    (outcome,) = outcomes(db_url, capsys, FakeTurnLoop(body="Done."))
    assert outcome in ("ok", "room_speaker")
