"""`Inference.speak`: routes in order, return only once bytes are ready, a failure before them moving on, a failure
after them cutting the stream and recording that route, ValueError before any call, and the spend row with
`characters`."""

from typing import Any, Literal

import pytest
from ashley.inference.inference import InferenceUnavailable
from ashley.inference.provider import Failure
from inference_support import ANY_TASK, COOLDOWN_S, FAILURES, Clock, FakeLedger, outcomes, route, settle
from contract_speech_support import FakeSpeechProvider, Say, drain, say_fail, speech_router, usage_of

VOICE = b"RIFF-voice-more"


def test_the_first_route_that_starts_is_her_voice_and_no_later_route_is_called() -> None:
    a, b = FakeSpeechProvider("a", says=[Say(media_type="audio/mpeg")]), FakeSpeechProvider("b")

    async def scenario() -> tuple[str, bytes]:
        speech = await speech_router([route("a"), route("b")], [a, b]).speak("speak", "hello")
        return speech.media_type, await drain(speech)

    assert settle(scenario()) == ("audio/mpeg", VOICE)
    assert b.said == []


def test_the_route_receives_its_model_voice_params_text_and_timeout() -> None:
    a = FakeSpeechProvider("a")
    inference = speech_router([route("a", "m2", 4.0, params={"voice": "ashley"})], [a])
    settle(inference.speak("speak", "say this"))
    assert [(s.model, dict(s.params), s.text, s.timeout_s) for s in a.said] == [("m2", {"voice": "ashley"}, "say this", 4.0)]


@pytest.mark.parametrize("failure", FAILURES)
@pytest.mark.parametrize("where", ["call", "first"])
def test_a_failure_before_the_first_bytes_moves_on_to_the_next_route(failure: Failure, where: Literal["call", "first"]) -> None:
    a = FakeSpeechProvider("a", says=[say_fail(failure, where)])
    b, ledger = FakeSpeechProvider("b", says=[Say(chunks=(b"from b",))]), FakeLedger()

    async def scenario() -> bytes:
        return await drain(await speech_router([route("a"), route("b")], [a, b], ledger).speak("speak", "hi"))

    assert settle(scenario()) == b"from b"
    assert outcomes(ledger) == [("a", "m1", failure), ("b", "m1", "ok")]


def test_speak_returns_with_the_first_bytes_already_ready_and_before_the_stream_ends() -> None:
    a, ledger = FakeSpeechProvider("a", says=[say_fail("error", "after")]), FakeLedger()

    async def scenario() -> list[tuple[str, str, str]]:
        speech = await speech_router([route("a")], [a], ledger).speak("speak", "hi")
        assert speech.media_type == "audio/wav"
        assert ledger.rows == [], "the call is still in flight: its row is written when its stream ends"
        await drain(speech)
        return outcomes(ledger)

    assert settle(scenario()) == [("a", "m1", "error")]


def test_no_route_starting_is_unavailable() -> None:
    a = FakeSpeechProvider("a", says=[say_fail("unavailable", "first")])
    with pytest.raises(InferenceUnavailable):
        settle(speech_router([route("ghost"), route("a")], [a]).speak("speak", "hi"))


def test_a_failure_after_audio_started_ends_the_stream_early_without_another_voice() -> None:
    a, b, ledger = FakeSpeechProvider("a", says=[say_fail("unavailable", "after")]), FakeSpeechProvider("b"), FakeLedger()

    async def scenario() -> bytes:
        return await drain(await speech_router([route("a"), route("b")], [a, b], ledger).speak("speak", "hi"))

    assert settle(scenario()) == VOICE
    assert b.said == []
    assert outcomes(ledger) == [("a", "m1", "unavailable")]


def test_a_mid_stream_unavailable_rests_that_provider_until_the_cooldown_passes() -> None:
    clock = Clock()
    a = FakeSpeechProvider("a", says=[say_fail("unavailable", "after"), Say(chunks=(b"back",))])
    b = FakeSpeechProvider("b", says=[Say(chunks=(b"b",))])
    inference = speech_router([route("a"), route("b")], [a, b], clock=clock)

    async def once() -> bytes:
        return await drain(await inference.speak("speak", "hi"))

    assert settle(once()) == VOICE
    assert settle(once()) == b"b"
    clock.advance(COOLDOWN_S + 1)
    assert settle(once()) == b"back"


def test_an_unavailable_before_bytes_rests_the_provider() -> None:
    a = FakeSpeechProvider("a", says=[say_fail("unavailable"), Say(chunks=(b"back",))])
    b = FakeSpeechProvider("b", says=[Say(chunks=(b"b",))])
    inference = speech_router([route("a"), route("b")], [a, b])

    async def once() -> bytes:
        return await drain(await inference.speak("speak", "hi"))

    assert (settle(once()), settle(once())) == (b"b", b"b")
    assert len(a.said) == 1


# --- ValueError before anything is called ----------------------------------------------------------------------


@pytest.mark.parametrize("task", ["transcribe", "chat", ANY_TASK])
def test_a_task_other_than_speak_is_a_value_error_before_any_call(task: Any) -> None:
    a, ledger = FakeSpeechProvider("a"), FakeLedger()
    with pytest.raises(ValueError):
        settle(speech_router([route("a")], [a], ledger).speak(task, "hi"))
    assert (a.said, ledger.rows) == ([], [])


def test_empty_text_is_a_value_error_before_any_call() -> None:
    a, ledger = FakeSpeechProvider("a"), FakeLedger()
    with pytest.raises(ValueError):
        settle(speech_router([route("a")], [a], ledger).speak("speak", ""))
    assert (a.said, ledger.rows) == ([], [])


# --- the route that started ------------------------------------------------------------------------------------


def test_the_speech_names_the_route_that_started() -> None:
    a, b = FakeSpeechProvider("a"), FakeSpeechProvider("b")
    speech = settle(speech_router([route("a", "m1"), route("b", "m2")], [a, b]).speak("speak", "hi"))
    assert (speech.provider, speech.model) == ("a", "m1")


def test_after_a_failure_before_audio_the_speech_names_the_second_route() -> None:
    a, b = FakeSpeechProvider("a", says=[say_fail("error", "first")]), FakeSpeechProvider("b")
    speech = settle(speech_router([route("a", "m1"), route("b", "m2")], [a, b]).speak("speak", "hi"))
    assert (speech.provider, speech.model) == ("b", "m2")


# --- the spend row ---------------------------------------------------------------------------------------------


def test_an_answered_call_is_one_ok_row_for_the_task_with_the_texts_length_as_characters() -> None:
    clock, ledger = Clock(), FakeLedger()
    a = FakeSpeechProvider("a", says=[Say(seconds=0.25)], clock=clock)

    async def scenario() -> None:
        await drain(await speech_router([route("a")], [a], ledger, clock).speak("speak", "twelve chars"))

    settle(scenario())
    [row] = ledger.rows
    assert (row.task, row.provider, row.model, row.outcome, row.duration_ms) == ("speak", "a", "m1", "ok", 250)
    assert usage_of(row, "characters") == len("twelve chars")


def test_every_call_made_is_a_row_each_carrying_the_same_character_count() -> None:
    ledger = FakeLedger()
    a, b = FakeSpeechProvider("a", says=[say_fail("error")]), FakeSpeechProvider("b")

    async def scenario() -> None:
        await drain(await speech_router([route("a"), route("b")], [a, b], ledger).speak("speak", "héllo"))

    settle(scenario())
    assert [(r.provider, r.outcome) for r in ledger.rows] == [("a", "error"), ("b", "ok")]
    assert [usage_of(r, "characters") for r in ledger.rows] == [5, 5]


def test_a_lost_ledger_row_does_not_cost_the_caller_the_voice() -> None:
    ledger = FakeLedger(fail_with=RuntimeError("down"))

    async def scenario() -> bytes:
        return await drain(await speech_router([route("a")], [FakeSpeechProvider("a")], ledger).speak("speak", "hi"))

    assert settle(scenario()) == VOICE
