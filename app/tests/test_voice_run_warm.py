"""A wake warms her turn's model while the person is still talking: once, with the Inbound she is then asked less its
words and voice match, never holding up the run, and the `voice.run` line says where the warm-up stood as she was asked."""

import asyncio
from collections.abc import Generator
from dataclasses import replace

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


def test_the_wake_warms_the_turn_she_is_then_asked(db_url: str) -> None:
    loop = FakeTurnLoop()
    carry(db_url, satellite_row(db_url, household(db_url)), FakeSpeech(), loop)
    [warmed], [asked] = loop.warmed, loop.asked
    assert (warmed.text, warmed.heard_as) == (".", None)
    assert replace(warmed, text=asked.text, heard_as=asked.heard_as) == asked


@pytest.mark.parametrize(("warms", "gate", "primed"), [(True, None, "ready"), (False, None, "none"),
                                                       (True, asyncio.Event(), "running")])
def test_the_run_line_says_where_the_warm_up_stood(db_url: str, capsys: pytest.CaptureFixture[str], warms: bool,
                                                   gate: asyncio.Event | None, primed: str) -> None:
    logs.setup()
    loop = FakeTurnLoop(warms=warms, warmed_gate=gate)
    carry(db_url, satellite_row(db_url, household(db_url)), FakeSpeech(), loop)
    [line] = events(capsys.readouterr().out, "voice.run")
    assert (line["outcome"], line["primed"]) == ("ok", primed)
    assert len(loop.asked) == 1
