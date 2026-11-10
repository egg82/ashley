"""`Inference.voiceprint` through the router and the shipped routes, and `SherpaVoiceEmbedder` with the real model when
the image's file is present."""

import math
import os
import random
import struct
from datetime import date
from pathlib import Path

import pytest
from ashley.inference import prices, routes
from ashley.inference.inference import InferenceUnavailable, NullInference
from ashley.inference.model import Usage
from ashley.inference.provider import ProviderFailed
from ashley.inference.sherpa_voiceprint import SherpaVoiceEmbedder
from ashley.inference.speech import AudioFormat
from ashley.settings import Settings
from speech_support import run
from voiceprint_support import ScriptedVoiceEmbedder, voiceprint_router

MODEL = Path(os.environ.get("VOICEPRINT_MODEL_PATH", Settings.voiceprint_model_path))
PCM = bytes(32000)
FORMAT = AudioFormat()


def test_the_first_route_that_answers_is_the_print_and_costs_one_row() -> None:
    first, second = ScriptedVoiceEmbedder("a"), ScriptedVoiceEmbedder("b")
    inference, ledger = voiceprint_router(first, second)
    print_ = run(inference.voiceprint(FORMAT, PCM))
    assert (print_.vector, print_.model, print_.audio_ms) == ((1.0, 0.0), "a-model", 1000)
    assert second.seen == [] and first.seen == [("a-model", 32000, FORMAT)]
    [call] = ledger.calls
    assert (call.task, call.provider, call.outcome) == ("voiceprint", "a", "ok")
    assert call.usage == Usage(0, 0, audio_ms=1000)


def test_a_failing_route_falls_through_and_none_answering_is_unavailable() -> None:
    down = ScriptedVoiceEmbedder("a", error=ProviderFailed("unavailable", "x"))
    inference, ledger = voiceprint_router(down, ScriptedVoiceEmbedder("b"))
    assert run(inference.voiceprint(FORMAT, PCM)).model == "b-model"
    assert [c.outcome for c in ledger.calls] == ["unavailable", "ok"]
    run(inference.voiceprint(FORMAT, PCM))
    assert len(down.seen) == 1
    with pytest.raises(InferenceUnavailable):
        run(voiceprint_router(ScriptedVoiceEmbedder("a", error=ProviderFailed("error", "x")))[0]
            .voiceprint(FORMAT, PCM))


def test_a_task_with_no_wired_route_is_unavailable() -> None:
    inference, ledger = voiceprint_router()
    with pytest.raises(InferenceUnavailable):
        run(inference.voiceprint(FORMAT, PCM))
    assert ledger.calls == []


@pytest.mark.parametrize("pcm", [b"", bytes(3)])
def test_no_audio_or_a_partial_frame_is_refused_before_any_call(pcm: bytes) -> None:
    provider = ScriptedVoiceEmbedder("a")
    inference, ledger = voiceprint_router(provider)
    with pytest.raises(ValueError):
        run(inference.voiceprint(FORMAT, pcm))
    assert provider.seen == [] and ledger.calls == []


def test_warming_asks_the_first_route_unbilled_and_only_known_tasks_may_be_warmed() -> None:
    inference, ledger = voiceprint_router(ScriptedVoiceEmbedder("a"))
    run(inference.warm("voiceprint"))
    assert ledger.calls == []
    with pytest.raises(ValueError):
        run(inference.warm("transcribe"))


def test_the_shipped_voiceprint_route_is_priced_at_zero_and_unwired_without_a_provider() -> None:
    loaded = routes.load({"sherpa": SherpaVoiceEmbedder("sherpa", "/nowhere")})
    [route] = loaded.for_task("voiceprint")
    assert route.provider == "sherpa"
    cost = prices.load().cost_usd(route.provider, route.model, Usage(0, 0, audio_ms=5000), date(2026, 10, 27))
    assert cost is not None and cost == 0
    with pytest.raises(InferenceUnavailable):
        run(NullInference().voiceprint(FORMAT, PCM))


def test_sherpa_takes_no_params_and_only_16khz_mono_16_bit() -> None:
    embedder = SherpaVoiceEmbedder("sherpa", "/nowhere")
    with pytest.raises(ValueError):
        embedder.check_voiceprint_params({"x": 1})
    for other in (AudioFormat(rate=8000), AudioFormat(width=1), AudioFormat(channels=2)):
        with pytest.raises(ProviderFailed) as failed:
            run(embedder.voiceprint("m", {}, PCM, other, 1.0))
        assert failed.value.failure == "error"


def test_a_missing_model_file_rests_the_provider_and_warms_as_unavailable() -> None:
    embedder = SherpaVoiceEmbedder("sherpa", "/nowhere/model.onnx")
    with pytest.raises(ProviderFailed) as failed:
        run(embedder.voiceprint("m", {}, PCM, FORMAT, 1.0))
    assert failed.value.failure == "unavailable"
    with pytest.raises(ProviderFailed):
        run(embedder.warm("m", {}, 1.0))


@pytest.mark.skipif(not MODEL.is_file(), reason=f"the speaker-embedding model is not at {MODEL}")
def test_audio_too_short_for_the_model_fails_the_call_without_resting_it() -> None:
    with pytest.raises(ProviderFailed) as failed:
        run(SherpaVoiceEmbedder("sherpa", str(MODEL)).voiceprint("m", {}, bytes(640), FORMAT, 10.0))
    assert failed.value.failure == "invalid_output"


@pytest.mark.skipif(not MODEL.is_file(), reason=f"the speaker-embedding model is not at {MODEL}")
def test_the_real_model_makes_a_unit_vector_that_tells_two_signals_apart() -> None:
    embedder = SherpaVoiceEmbedder("sherpa", str(MODEL))
    rng = random.Random(7)
    hum = struct.pack("<16000h", *(int(8000 * math.sin(i * 0.05) + rng.gauss(0, 300)) for i in range(16000)))
    hiss = struct.pack("<16000h", *(int(rng.gauss(0, 2000)) for _ in range(16000)))
    a = run(embedder.voiceprint("m", {}, hum, FORMAT, 10.0))
    again = run(embedder.voiceprint("m", {}, hum, FORMAT, 10.0))
    b = run(embedder.voiceprint("m", {}, hiss, FORMAT, 10.0))
    assert len(a) > 100 and math.isclose(math.hypot(*a), 1.0)
    assert math.isclose(sum(x * y for x, y in zip(a, again)), 1.0, abs_tol=1e-4)
    assert sum(x * y for x, y in zip(a, b)) < 0.99
