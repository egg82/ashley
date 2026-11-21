"""`Reply.ask` names a fixed ask (the time, the date) the person made. It is only counted: the reply is unchanged and
`respond.done` and `voice.run` carry it."""

import asyncio
import json
from collections.abc import Callable
from typing import Any

import pytest
from ashley import logs, services
from ashley.channels.respond import respond
from ashley.channels.voice.clips import Clips
from ashley.inference import anthropic_wire, openai_wire
from ashley.inference.inference import Inference
from ashley.inference.reply import Ask, Reply
from contract.conversations_support import db_url as db_url, events, household
from contract.conversations_support import migrated_template as migrated_template
from respond_support import Fakes, inbound, wired as wired
from voice_support import FakeSpeech, FakeTurnLoop, satellite_row
from test_voice_run import carry

ASKS: tuple[Ask, ...] = ("none", "time", "date")


@pytest.fixture
def speech_unwired():
    yield
    services.unregister(Inference)
    services.unregister(Clips)


@pytest.mark.parametrize("ask", ASKS)
def test_the_turn_log_counts_the_ask_and_the_reply_is_unchanged(wired: Fakes, ask: Ask,
                                                                capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    wired.inference.script = [Reply(spoken="It is noon.", text="It is noon.", ask=ask)]
    out = asyncio.run(respond(inbound(medium="spoken")))
    assert out.body == "It is noon." and out.ask == ask
    [done] = events(capsys.readouterr().out, "respond.done")
    assert done["ask"] == ask


@pytest.mark.parametrize("ask", ASKS)
def test_the_voice_run_logs_the_ask(db_url: str, speech_unwired: None, ask: Ask,
                                    capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    carry(db_url, satellite_row(db_url, household(db_url)), FakeSpeech(), FakeTurnLoop(ask=ask))
    [run] = events(capsys.readouterr().out, "voice.run")
    assert run["ask"] == ask and run["outcome"] == "ok"


def test_an_ask_defaults_to_none() -> None:
    assert Reply(spoken="x", text="x").ask == "none"


@pytest.mark.parametrize("build", (anthropic_wire.reply_schema, openai_wire.reply_schema),
                         ids=("anthropic", "openai-compatible"))
def test_the_field_is_a_required_enum_on_every_wire(build: Callable[[type[Reply]], object]) -> None:
    schema: Any = json.loads(json.dumps(build(Reply)))
    ask = schema["properties"]["ask"]
    assert ask["enum"] == list(ASKS) and "ask" in schema["required"] and "default" not in ask
