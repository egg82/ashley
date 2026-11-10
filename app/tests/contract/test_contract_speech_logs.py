"""Speech logs: `inference.call` per call made with `audio_ms` or `characters`, `inference.route_skipped` per skip,
and no audio, transcript or spoken text in any log record on any path."""

import logging
from collections.abc import Iterator

import pytest
from ashley import logs
from ashley.inference.inference import InferenceUnavailable
from conversations_support import events
from inference_support import FakeLedger, route, settle
from contract_speech_support import (CHUNKS_MS, MARK, FakeSpeechProvider, Hear, Say, Utterance, drain,
                            hear_fail, say_fail, speech_router)
from test_contract_inference_logs import everything_logged


@pytest.fixture
def debug_logging() -> Iterator[None]:
    logs.setup({"LOG_LEVEL": "DEBUG"})
    yield
    logs.setup({})


def test_a_transcribe_call_logs_task_provider_model_outcome_audio_ms_and_duration(
        capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    inference = speech_router([route("ghost", "gm"), route("a", "m1")], [FakeSpeechProvider("a", [Hear("hi")])])
    capsys.readouterr()
    settle(inference.transcribe("transcribe", Utterance().heard))
    out = capsys.readouterr().out
    [line] = events(out, "inference.call")
    assert (line["task"], line["provider"], line["model"], line["outcome"]) == ("transcribe", "a", "m1", "ok")
    assert line["audio_ms"] == str(CHUNKS_MS)
    assert "duration_ms" in line
    [skipped] = events(out, "inference.route_skipped")
    assert (skipped["task"], skipped["provider"], skipped["reason"]) == ("transcribe", "ghost", "unwired")


def test_a_speak_call_logs_characters_and_one_line_per_call_made(capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    a, b = FakeSpeechProvider("a", says=[say_fail("error", "first")]), FakeSpeechProvider("b")
    inference = speech_router([route("a"), route("b")], [a, b])
    capsys.readouterr()

    async def scenario() -> None:
        await drain(await inference.speak("speak", "hello"))

    settle(scenario())
    lines = events(capsys.readouterr().out, "inference.call")
    assert [(ln["provider"], ln["outcome"], ln["characters"]) for ln in lines] == [("a", "error", "5"), ("b", "ok", "5")]


def leaky_scenario() -> None:
    """Every speech path with the marker in the audio, the transcripts and the spoken text."""
    pcm = (MARK.encode() * 4000,)
    said = f"say {MARK}"
    transcribing = FakeSpeechProvider("a", [hear_fail("unavailable")])
    answering = FakeSpeechProvider("c", [Hear(f"heard {MARK}")])
    inference = speech_router([route("ghost"), route("a"), route("c")], [transcribing, answering],
                              FakeLedger(fail_with=RuntimeError("down")))
    for _ in range(2):
        settle(inference.transcribe("transcribe", Utterance(pcm).heard))
    speaking = FakeSpeechProvider("b", says=[say_fail("error", "first"), Say(chunks=(MARK.encode(),), where="after",
                                                                         error=say_fail("error").error)])
    voiced = speech_router([route("b"), route("d")], [speaking, FakeSpeechProvider("d")])

    async def speak() -> None:
        await drain(await voiced.speak("speak", said))
        await drain(await voiced.speak("speak", said))

    settle(speak())
    with pytest.raises(InferenceUnavailable):
        settle(speech_router([route("ghost")], []).speak("speak", said))
    with pytest.raises(ValueError):
        settle(voiced.speak("speak", ""))


def test_no_audio_transcript_or_spoken_text_reaches_any_log_line(
        debug_logging: None, capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    capsys.readouterr()
    leaky_scenario()
    out = capsys.readouterr().out
    assert len(events(out, "inference.call")) >= 3, "control: the calls were logged"
    assert len(events(out, "inference.route_skipped")) >= 1, "control: the skips were logged"
    assert MARK not in everything_logged(out, caplog)
