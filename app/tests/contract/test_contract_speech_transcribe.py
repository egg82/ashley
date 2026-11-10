"""`Inference.transcribe`: routes in order, fallback that loses no audio, resting, an empty transcript as an answer,
ValueError before any call, and the spend row with `audio_ms`."""

from typing import Any

import pytest
from ashley.inference.inference import InferenceUnavailable
from ashley.inference.provider import Failure
from inference_support import ANY_TASK, COOLDOWN_S, FAILURES, Clock, FakeLedger, outcomes, route, settle
from contract_speech_support import (CHUNKS, CHUNKS_MS, FORMAT, FakeSpeechProvider, Hear, Utterance,
                            hear_fail, speech_router, usage_of)


def test_the_first_route_that_answers_is_the_transcript_and_no_later_route_is_called() -> None:
    a, b = FakeSpeechProvider("a", [Hear("from a")]), FakeSpeechProvider("b", [Hear("from b")])
    heard = Utterance()
    got = settle(speech_router([route("a"), route("b")], [a, b]).transcribe("transcribe", heard.heard))
    assert got.text == "from a"
    assert (len(a.heard), len(b.heard)) == (1, 0)


def test_the_route_receives_its_model_params_timeout_format_and_the_audio() -> None:
    a = FakeSpeechProvider("a")
    heard = Utterance()
    settle(speech_router([route("a", "m2", 7.5, params={"lang": "en"})], [a]).transcribe("transcribe", heard.heard))
    assert [(h.model, dict(h.params), h.timeout_s, h.format, h.pcm) for h in a.heard] == [
        ("m2", {"lang": "en"}, 7.5, FORMAT, heard.pcm)]


@pytest.mark.parametrize("failure", FAILURES)
def test_each_failure_kind_moves_on_to_the_next_route(failure: Failure) -> None:
    a, b = FakeSpeechProvider("a", [hear_fail(failure)]), FakeSpeechProvider("b", [Hear("from b")])
    ledger = FakeLedger()
    got = settle(speech_router([route("a"), route("b")], [a, b], ledger).transcribe("transcribe", Utterance().heard))
    assert got.text == "from b"
    assert outcomes(ledger) == [("a", "m1", failure), ("b", "m1", "ok")]


def test_routes_are_tried_in_the_configured_order() -> None:
    providers = [FakeSpeechProvider(n, [hear_fail("error")]) for n in ("x", "y", "z")]
    ledger = FakeLedger()
    inference = speech_router([route("z"), route("x", "m2"), route("y")], providers, ledger)
    with pytest.raises(InferenceUnavailable):
        settle(inference.transcribe("transcribe", Utterance().heard))
    assert outcomes(ledger) == [("z", "m1", "error"), ("x", "m2", "error"), ("y", "m1", "error")]


def test_an_unwired_provider_is_skipped_without_a_call_or_a_row() -> None:
    b, ledger = FakeSpeechProvider("b", [Hear("from b")]), FakeLedger()
    got = settle(speech_router([route("ghost"), route("b")], [b], ledger).transcribe("transcribe", Utterance().heard))
    assert got.text == "from b"
    assert outcomes(ledger) == [("b", "m1", "ok")]


def test_no_route_answering_is_unavailable() -> None:
    with pytest.raises(InferenceUnavailable):
        settle(speech_router([route("ghost")], []).transcribe("transcribe", Utterance().heard))


# --- the first route is fed as the audio arrives; the next gets all of it --------------------------------------


def test_the_first_route_reads_the_chunks_as_they_arrive_not_ahead_of_itself() -> None:
    utterance = Utterance()
    a = FakeSpeechProvider("a", [Hear(read=2)], watching=utterance)
    settle(speech_router([route("a")], [a]).transcribe("transcribe", utterance.heard))
    assert a.pulled_when_done == [2]


def test_the_next_route_gets_the_whole_utterance_read_so_far_plus_the_rest() -> None:
    utterance = Utterance()
    a = FakeSpeechProvider("a", [Hear(read=2, error=hear_fail("unavailable").error)])
    b = FakeSpeechProvider("b", [Hear("from b")])
    got = settle(speech_router([route("a"), route("b")], [a, b]).transcribe("transcribe", utterance.heard))
    assert got.text == "from b"
    assert b.heard[0].pcm == b"".join(CHUNKS)
    assert b.heard[0].format == FORMAT


def test_a_third_route_still_gets_every_byte_after_two_failures() -> None:
    utterance = Utterance()
    a = FakeSpeechProvider("a", [Hear(read=1, error=hear_fail("error").error)])
    b = FakeSpeechProvider("b", [Hear(read=3, error=hear_fail("invalid_output").error)])
    c = FakeSpeechProvider("c", [Hear("from c")])
    settle(speech_router([route("a"), route("b"), route("c")], [a, b, c]).transcribe("transcribe", utterance.heard))
    assert c.heard[0].pcm == utterance.pcm


def test_transcribe_returns_only_after_the_chunks_have_ended() -> None:
    utterance = Utterance()
    a = FakeSpeechProvider("a", [Hear("early", read=1)])
    settle(speech_router([route("a")], [a]).transcribe("transcribe", utterance.heard))
    assert utterance.pulled == len(CHUNKS)


# --- resting ---------------------------------------------------------------------------------------------------


def test_a_provider_that_failed_unavailable_rests_for_the_cooldown_then_is_asked_again() -> None:
    clock = Clock()
    a, b = FakeSpeechProvider("a", [hear_fail("unavailable"), Hear("a back")]), FakeSpeechProvider("b", [Hear("b")])
    inference = speech_router([route("a"), route("b")], [a, b], clock=clock)
    assert settle(inference.transcribe("transcribe", Utterance().heard)).text == "b"
    assert settle(inference.transcribe("transcribe", Utterance().heard)).text == "b"
    assert len(a.heard) == 1, "resting: not called again"
    clock.advance(COOLDOWN_S + 1)
    assert settle(inference.transcribe("transcribe", Utterance().heard)).text == "a back"


@pytest.mark.parametrize("failure", ["invalid_output", "error"])
def test_other_failures_do_not_rest_the_provider(failure: Failure) -> None:
    a = FakeSpeechProvider("a", [hear_fail(failure), Hear("again")])
    inference = speech_router([route("a"), route("b")], [a, FakeSpeechProvider("b")])
    settle(inference.transcribe("transcribe", Utterance().heard))
    assert settle(inference.transcribe("transcribe", Utterance().heard)).text == "again"


# --- an empty transcript ---------------------------------------------------------------------------------------


def test_an_empty_transcript_is_an_answer_so_no_later_route_is_asked_and_the_row_is_ok() -> None:
    a, b, ledger = FakeSpeechProvider("a", [Hear("")]), FakeSpeechProvider("b"), FakeLedger()
    got = settle(speech_router([route("a"), route("b")], [a, b], ledger).transcribe("transcribe", Utterance().heard))
    assert got.text == ""
    assert b.heard == []
    assert outcomes(ledger) == [("a", "m1", "ok")]


def test_a_transcript_is_stripped() -> None:
    a = FakeSpeechProvider("a", [Hear("  turn on the lamp \n")])
    got = settle(speech_router([route("a")], [a]).transcribe("transcribe", Utterance().heard))
    assert got.text == "turn on the lamp"


# --- ValueError before anything is called ----------------------------------------------------------------------


@pytest.mark.parametrize("task", ["speak", "chat", ANY_TASK])
def test_a_task_other_than_transcribe_is_a_value_error_before_any_call_or_read(task: Any) -> None:
    utterance, a, ledger = Utterance(), FakeSpeechProvider("a"), FakeLedger()
    with pytest.raises(ValueError):
        settle(speech_router([route("a")], [a], ledger).transcribe(task, utterance.heard))
    assert (a.heard, ledger.rows, utterance.pulled) == ([], [], 0)


# --- the route that answered -----------------------------------------------------------------------------------


def test_the_transcript_names_the_first_route_that_answered() -> None:
    a, b = FakeSpeechProvider("a"), FakeSpeechProvider("b")
    got = settle(speech_router([route("a", "m1"), route("b", "m2")], [a, b]).transcribe("transcribe", Utterance().heard))
    assert (got.provider, got.model) == ("a", "m1")


def test_after_a_fallback_the_transcript_names_the_route_that_answered() -> None:
    a, b = FakeSpeechProvider("a", [hear_fail("error")]), FakeSpeechProvider("b")
    got = settle(speech_router([route("a", "m1"), route("b", "m2")], [a, b]).transcribe("transcribe", Utterance().heard))
    assert (got.provider, got.model) == ("b", "m2")


# --- the spend row ---------------------------------------------------------------------------------------------


def test_an_answered_call_is_one_ok_row_for_the_task_carrying_the_utterances_duration() -> None:
    clock, ledger = Clock(), FakeLedger()
    a = FakeSpeechProvider("a", [Hear("hi", seconds=0.25)], clock=clock)
    settle(speech_router([route("a")], [a], ledger, clock).transcribe(
        "transcribe", Utterance().heard))
    [row] = ledger.rows
    assert (row.task, row.provider, row.model, row.outcome, row.duration_ms) == ("transcribe", "a", "m1", "ok", 250)
    assert usage_of(row, "audio_ms") == CHUNKS_MS


def test_every_call_made_is_a_row_and_the_fallback_row_carries_the_whole_utterance() -> None:
    ledger = FakeLedger()
    a = FakeSpeechProvider("a", [hear_fail("unavailable")])
    b = FakeSpeechProvider("b")
    settle(speech_router([route("a"), route("b")], [a, b], ledger).transcribe("transcribe", Utterance().heard))
    assert [(r.provider, r.outcome) for r in ledger.rows] == [("a", "unavailable"), ("b", "ok")]
    assert usage_of(ledger.rows[1], "audio_ms") == CHUNKS_MS


def test_a_lost_ledger_row_does_not_cost_the_caller_the_transcript() -> None:
    ledger = FakeLedger(fail_with=RuntimeError("down"))
    a = FakeSpeechProvider("a", [Hear("still here")])
    assert settle(speech_router([route("a")], [a], ledger).transcribe(
        "transcribe", Utterance().heard)).text == "still here"
