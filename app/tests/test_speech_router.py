"""`RoutedInference.transcribe` and `speak`: routes in order, fallback without losing audio, resting, and one spend row
per call, over scripted providers."""

from collections.abc import AsyncGenerator, AsyncIterator
from typing import Any
import logging

import pytest
from ashley.inference.inference import Inference, InferenceUnavailable
from ashley.inference.model import Message, Prompt, SystemPrompt
from ashley.inference.reply import Reply
from ashley.inference.speech import Heard, SpeechTask, Transcript
from speech_support import (FORMAT, MS, PCM, ScriptedSpeaker, ScriptedTranscriber, failing, heard, pcm, router, run,
                            usage_of)


def listen(inference: Inference, utterance: Heard) -> Transcript:
    return run(inference.transcribe("transcribe", utterance))


def test_the_first_route_that_answers_is_the_transcript_and_costs_one_row() -> None:
    first, second = ScriptedTranscriber("a", " hello "), ScriptedTranscriber("b")
    inference, ledger = router("transcribe", first, second)
    assert listen(inference, heard()).text == "hello"
    assert second.seen == []
    [call] = ledger.calls
    assert (call.task, call.provider, call.model, call.outcome) == ("transcribe", "a", "a-model", "ok")
    assert usage_of(call).audio_ms == MS and call.cost_usd is None


def test_an_empty_transcript_is_an_answer() -> None:
    inference, ledger = router("transcribe", ScriptedTranscriber("a", "  "), ScriptedTranscriber("b"))
    assert listen(inference, heard()).text == ""
    assert [c.provider for c in ledger.calls] == ["a"]


def test_a_failing_route_hands_the_next_all_the_audio_including_what_it_already_read() -> None:
    first = ScriptedTranscriber("a", error=failing("error"), read=2)
    second = ScriptedTranscriber("b", "from b")
    inference, ledger = router("transcribe", first, second)
    assert listen(inference, heard()).text == "from b"
    assert first.seen == PCM[:2] and second.seen == PCM
    assert [(c.provider, c.outcome) for c in ledger.calls] == [("a", "error"), ("b", "ok")]
    assert [usage_of(c).audio_ms for c in ledger.calls] == [2 * 50, MS]


def test_a_provider_that_failed_unavailable_rests_for_the_next_call() -> None:
    first, second = ScriptedTranscriber("a", error=failing("unavailable")), ScriptedTranscriber("b")
    inference, ledger = router("transcribe", first, second)
    listen(inference, heard())
    listen(inference, heard())
    assert [c.provider for c in ledger.calls] == ["a", "b", "b"]


def test_no_route_answering_is_unavailable_and_the_audio_is_still_read_to_its_end() -> None:
    consumed: list[bytes] = []

    async def watched() -> AsyncIterator[bytes]:
        async for chunk in pcm():
            consumed.append(chunk)
            yield chunk

    inference, _ = router("transcribe", ScriptedTranscriber("a", error=failing("error"), read=1))
    with pytest.raises(InferenceUnavailable):
        listen(inference, Heard(FORMAT, watched()))
    assert consumed == PCM


def test_the_language_of_the_utterance_reaches_every_route_that_is_tried() -> None:
    first, second = ScriptedTranscriber("a", error=failing("unavailable")), ScriptedTranscriber("b")
    inference, _ = router("transcribe", first, second)
    listen(inference, Heard(FORMAT, pcm(PCM), "de"))
    assert (first.languages, second.languages) == (["de"], ["de"])
    listen(inference, heard())
    assert second.languages == ["de", None]


def test_an_unwired_route_is_skipped_and_none_wired_is_unavailable() -> None:
    inference, ledger = router("transcribe", ScriptedTranscriber("b"), names=["a", "b"])
    assert listen(inference, heard()).text == "scripted"
    assert [c.provider for c in ledger.calls] == ["b"]
    nothing, _ = router("transcribe", names=["a"])
    with pytest.raises(InferenceUnavailable):
        listen(nothing, heard())


def test_a_provider_without_the_ability_is_skipped_not_called() -> None:
    inference, ledger = router("transcribe", ScriptedSpeaker("a"), ScriptedTranscriber("b"), names=["a", "b"])
    assert listen(inference, heard()).text == "scripted"
    assert [c.provider for c in ledger.calls] == ["b"]


def test_a_broken_audio_source_is_its_own_error_and_blames_no_provider() -> None:
    class Gone(Exception):
        pass

    async def broken() -> AsyncIterator[bytes]:
        yield PCM[0]
        raise Gone

    first = ScriptedTranscriber("a")
    inference, ledger = router("transcribe", first, ScriptedTranscriber("b"))
    with pytest.raises(Gone):
        listen(inference, Heard(FORMAT, broken()))
    assert ledger.calls == []
    assert listen(inference, heard()).text == "scripted"
    assert [c.provider for c in ledger.calls] == ["a"]


def test_text_and_speech_tasks_are_kept_apart() -> None:
    inference, _ = router("transcribe", ScriptedTranscriber("a"))
    prompt = Prompt({"default": SystemPrompt("s")}, (Message("person", "hi"),))
    speech_task: Any = "transcribe"
    with pytest.raises(ValueError):
        run(inference.generate(speech_task, prompt, Reply))
    with pytest.raises(ValueError):
        run(inference.step(speech_task, prompt, Reply))
    wrong: SpeechTask = "speak"
    with pytest.raises(ValueError):
        run(inference.transcribe(wrong, heard()))
    with pytest.raises(ValueError):
        run(inference.speak("transcribe", "hi"))


def speak(inference: Inference, text: str = "Hello.") -> list[bytes]:
    async def scenario() -> list[bytes]:
        return [c async for c in (await inference.speak("speak", text)).chunks]

    return run(scenario())


def test_speaking_streams_the_first_route_and_writes_its_row_when_the_stream_ends() -> None:
    provider = ScriptedSpeaker("e")
    inference, ledger = router("speak", provider)

    async def scenario() -> None:
        speech = await inference.speak("speak", "Hello.")
        assert speech.media_type == "audio/mpeg" and ledger.calls == []
        assert [c async for c in speech.chunks] == [b"ab", b"cd"]

    run(scenario())
    [call] = ledger.calls
    assert (call.task, call.provider, call.outcome, usage_of(call).characters) == ("speak", "e", "ok", 6)
    assert provider.closed == 1


def test_a_route_that_fails_before_starting_moves_on() -> None:
    inference, ledger = router("speak", ScriptedSpeaker("a", error=failing("unavailable")), ScriptedSpeaker("b"))
    assert speak(inference) == [b"ab", b"cd"]
    assert [(c.provider, c.outcome) for c in ledger.calls] == [("a", "unavailable"), ("b", "ok")]


def test_a_break_after_audio_started_ends_the_stream_early_and_is_that_routes_failure() -> None:
    inference, ledger = router("speak", ScriptedSpeaker("a", after=failing("unavailable")), ScriptedSpeaker("b"))
    assert speak(inference) == [b"ab", b"cd"]
    assert [(c.provider, c.outcome) for c in ledger.calls] == [("a", "unavailable")]
    assert speak(inference) == [b"ab", b"cd"]
    assert [c.provider for c in ledger.calls] == ["a", "b"], "the broken provider rests"


def test_a_listener_that_stops_early_still_closes_the_provider_and_records_the_call() -> None:
    provider = ScriptedSpeaker("a")
    inference, ledger = router("speak", provider)

    async def scenario() -> None:
        speech = await inference.speak("speak", "Hello.")
        chunks = speech.chunks
        assert await anext(chunks) == b"ab"
        assert isinstance(chunks, AsyncGenerator)
        await chunks.aclose()

    run(scenario())
    assert provider.closed == 1 and [c.outcome for c in ledger.calls] == ["ok"]


def test_no_route_starting_is_unavailable_and_empty_text_is_refused_first() -> None:
    inference, _ = router("speak", ScriptedSpeaker("a", error=failing("error")))
    with pytest.raises(InferenceUnavailable):
        speak(inference)
    with pytest.raises(ValueError):
        speak(inference, "")


def test_logs_carry_counts_and_never_the_words(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    inference, _ = router("transcribe", ScriptedTranscriber("a", "my secret words"))
    listen(inference, heard())
    spoken, _ = router("speak", ScriptedSpeaker("e"))
    speak(spoken, "my other secret words")
    text = "\n".join(f"{r.getMessage()} {getattr(r, 'fields', '')}" for r in caplog.records)
    assert "audio_ms" in text and "characters" in text
    assert "secret" not in text
