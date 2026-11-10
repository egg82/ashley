"""`Inference.warm("speak")`: the one route `speak` would try first is warmed with its own timeout, best effort and
never raising, with no spend row and no resting, and one `inference.warm` line; the base classes prepare nothing."""

from typing import Any

import pytest
from ashley import logs
from ashley.inference.inference import Inference
from ashley.inference.provider import Failure, ProviderFailed
from ashley.inference.speech_provider import Speaker, SpeechStream
from conversations_support import events
from contract_speech_support import FakeSpeechProvider, drain, say_fail, speech_router
from inference_support import ANY_TASK, COOLDOWN_S, FAILURES, Clock, FakeLedger, route, settle
from collections.abc import Mapping


def failed(failure: Failure) -> ProviderFailed:
    return ProviderFailed(failure, f"{failure} (status 000)", None)


def test_the_first_route_speak_would_try_is_warmed_with_its_timeout_and_no_other() -> None:
    a, b = FakeSpeechProvider("a"), FakeSpeechProvider("b")
    settle(speech_router([route("a", timeout_s=4.0), route("b", timeout_s=9.0)], [a, b]).warm("speak"))
    assert (a.warmed, b.warmed) == ([4.0], [])


def test_an_unwired_route_is_passed_over_for_the_next_wired_one() -> None:
    a = FakeSpeechProvider("a")
    settle(speech_router([route("ghost"), route("a", timeout_s=3.0)], [a]).warm("speak"))
    assert a.warmed == [3.0]


def test_a_resting_provider_is_passed_over_until_its_cooldown_passes() -> None:
    clock = Clock()
    a, b = FakeSpeechProvider("a", says=[say_fail("unavailable")]), FakeSpeechProvider("b")
    inference = speech_router([route("a"), route("b")], [a, b], clock=clock)
    settle(inference.speak("speak", "hi"))
    settle(inference.warm("speak"))
    assert (a.warmed, b.warmed) == ([], [10.0])
    clock.advance(COOLDOWN_S + 1)
    settle(inference.warm("speak"))
    assert (a.warmed, b.warmed) == ([10.0], [10.0])


@pytest.mark.parametrize("failure", FAILURES)
def test_a_failed_warm_is_swallowed_and_the_next_route_is_not_tried(failure: Failure) -> None:
    a, b = FakeSpeechProvider("a", warm_error=failed(failure)), FakeSpeechProvider("b")
    assert settle(speech_router([route("a"), route("b")], [a, b]).warm("speak")) is None
    assert (len(a.warmed), b.warmed) == (1, [])


def test_any_other_exception_from_the_provider_is_swallowed_too() -> None:
    a = FakeSpeechProvider("a", warm_error=RuntimeError("boom"))
    assert settle(speech_router([route("a")], [a]).warm("speak")) is None
    assert len(a.warmed) == 1


def test_no_route_available_is_not_an_error_and_warms_nothing() -> None:
    assert settle(speech_router([route("ghost")], []).warm("speak")) is None


@pytest.mark.parametrize("task", ["transcribe", "chat", ANY_TASK])
def test_a_task_other_than_speak_is_a_value_error_before_anything_is_warmed(
        task: Any, capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    a, ledger = FakeSpeechProvider("a"), FakeLedger()
    capsys.readouterr()
    with pytest.raises(ValueError):
        settle(speech_router([route("a")], [a], ledger).warm(task))
    assert (a.warmed, ledger.rows, events(capsys.readouterr().out, "inference.warm")) == ([], [], [])


@pytest.mark.parametrize("error", [None, failed("unavailable"), RuntimeError("boom")])
def test_warming_writes_no_spend_row(error: Exception | None) -> None:
    ledger = FakeLedger()
    a = FakeSpeechProvider("a", warm_error=error)
    settle(speech_router([route("a")], [a], ledger).warm("speak"))
    assert (len(a.warmed), ledger.rows, ledger.attempts) == (1, [], 0)


def test_a_failed_warm_does_not_make_the_provider_rest() -> None:
    a, b = FakeSpeechProvider("a", warm_error=failed("unavailable")), FakeSpeechProvider("b")
    inference = speech_router([route("a"), route("b")], [a, b])

    async def scenario() -> bytes:
        await inference.warm("speak")
        return await drain(await inference.speak("speak", "hi"))

    assert settle(scenario()) == b"RIFF-voice-more"
    assert (len(a.said), b.said) == (1, [])
    settle(inference.warm("speak"))
    assert (len(a.warmed), b.warmed) == (2, [])


# --- the log line ----------------------------------------------------------------------------------------------


def test_a_warm_logs_provider_model_ok_and_the_duration(capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    clock = Clock()
    a = FakeSpeechProvider("a", clock=clock, warm_seconds=0.25)
    inference = speech_router([route("ghost"), route("a", "m2")], [a], clock=clock)
    capsys.readouterr()
    settle(inference.warm("speak"))
    [line] = events(capsys.readouterr().out, "inference.warm")
    assert (line["provider"], line["model"], line["outcome"], line["duration_ms"]) == ("a", "m2", "ok", "250")


@pytest.mark.parametrize("failure", FAILURES)
def test_a_failed_warm_logs_its_failure_kind_as_the_outcome(failure: Failure,
                                                            capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    inference = speech_router([route("a")], [FakeSpeechProvider("a", warm_error=failed(failure))])
    capsys.readouterr()
    settle(inference.warm("speak"))
    [line] = events(capsys.readouterr().out, "inference.warm")
    assert (line["provider"], line["outcome"]) == ("a", failure)


def test_one_warm_is_one_line_and_none_is_logged_when_no_route_is_available(
        capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    capsys.readouterr()
    settle(speech_router([route("ghost")], []).warm("speak"))
    assert events(capsys.readouterr().out, "inference.warm") == []
    inference = speech_router([route("a"), route("b")], [FakeSpeechProvider("a"), FakeSpeechProvider("b")])
    settle(inference.warm("speak"))
    assert len(events(capsys.readouterr().out, "inference.warm")) == 1


# --- the base classes ------------------------------------------------------------------------------------------


def test_the_base_inference_warm_prepares_nothing_and_still_refuses_other_tasks() -> None:
    class Plain(Inference):
        async def generate(self, task: Any, prompt: Any, output: Any, *, conversation_id: int | None = None) -> Any:
            raise AssertionError("not used")

        async def step(self, task: Any, prompt: Any, output: Any, *, conversation_id: int | None = None) -> Any:
            raise AssertionError("not used")

        async def transcribe(self, task: Any, heard: Any, *, conversation_id: int | None = None) -> Any:
            raise AssertionError("not used")

        async def speak(self, task: Any, text: str, *, conversation_id: int | None = None) -> Any:
            raise AssertionError("warm must not speak")

    plain = Plain()
    assert settle(plain.warm("speak")) is None
    wrong: Any = "transcribe"
    with pytest.raises(ValueError):
        settle(plain.warm(wrong))


def test_the_base_speaker_warm_prepares_nothing() -> None:
    class Plain(Speaker):
        @property
        def name(self) -> str:
            return "plain"

        def check_speak_params(self, params: Mapping[str, object]) -> None:
            return None

        async def speak(self, model: str, params: Mapping[str, object], text: str, timeout_s: float) -> SpeechStream:
            raise AssertionError("warm must not speak")

    assert settle(Plain().warm(1.0)) is None
