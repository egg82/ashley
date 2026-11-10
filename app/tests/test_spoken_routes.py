"""Tap to talk's routes through the real app, with a fake `Inference` and fake devices behind the locator: a WAV of
16 kHz 16-bit mono PCM is transcribed and the words come back; nothing else is (size and duration caps, other formats);
a transcription failure is 503; sign-in, the same-site rule (an `audio/wav` body, not JSON), the kiosk's device rules
and rate; no turn is run (the page sends the words as a typed message); and the logs carry sizes, never words."""

import io
import wave
from collections.abc import Generator
from dataclasses import dataclass, field, replace

import pytest
from ashley import services
from ashley.api import spoken as spoken_route
from ashley.api.kiosk_device import KIOSK_COOKIE
from ashley.api.models import ErrorResponse
from ashley.api.spoken_models import SpokenLimits, Transcript
from ashley.api.person import person_speaking
from ashley.channels import spoken
from ashley.channels.devices import Devices
from ashley.channels.voice import config as voice_config
from ashley.conversations.conversations import Conversations
from ashley.inference.inference import Inference, InferenceUnavailable
from ashley.inference.speech import AudioFormat, Heard, SpeechTask
from ashley.inference.speech import Transcript as Words
from ashley.main import create_app
from ashley.settings import Settings
from ashley.signin.model import SignedIn
from fastapi.testclient import TestClient
from respond_support import ALANA, FakeConversations, FakeInference
from test_kiosk_routes import DEVICE, TOKEN, FakeDevices

PUBLIC = "https://ashley.test"
SAID = "zqTURN the hall light on"


@dataclass
class Hearing(FakeInference):
    """Transcribes to `words`, or raises `error`; `heard` is each utterance's (format, bytes)."""

    words: str = SAID
    error: Exception | None = None
    heard: list[tuple[AudioFormat, bytes]] = field(default_factory=list[tuple[AudioFormat, bytes]])

    async def transcribe(self, task: SpeechTask, heard: Heard, *, conversation_id: int | None = None) -> Words:
        assert task == "transcribe"
        self.heard.append((heard.format, b"".join([c async for c in heard.chunks])))
        if self.error is not None:
            raise self.error
        return Words(self.words, "fake", "fake")


def wav(ms: int, rate: int = 16000, width: int = 2, channels: int = 1) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setframerate(rate)
        w.setsampwidth(width)
        w.setnchannels(channels)
        w.writeframes(b"\x01\x00" * (rate * ms // 1000) * channels * (width // 2 or 1))
    return out.getvalue()


@pytest.fixture
def hearing(monkeypatch: pytest.MonkeyPatch) -> Generator[Hearing]:
    monkeypatch.setattr(spoken_route, "CAPS", spoken.Caps(max_ms=1000, quiet_rms=0.05, voice_s=120))
    yield Hearing()
    for interface in (Devices, Conversations, Inference):
        services.unregister(interface)


@pytest.fixture
def devices() -> FakeDevices:
    return FakeDevices()


@pytest.fixture
def conversations() -> FakeConversations:
    return FakeConversations()


def _app(hearing: Hearing, devices: FakeDevices, conversations: FakeConversations, *, person: bool = True,
         kiosk: bool = True) -> TestClient:
    app = create_app(Settings(database_url="", build_version="test", public_url=PUBLIC))
    services.register(Inference, hearing)
    services.register(Devices, devices)
    services.register(Conversations, conversations)
    if person:
        app.dependency_overrides[person_speaking] = lambda: SignedIn(1, ALANA)
    client = TestClient(app, base_url=PUBLIC, headers={"origin": PUBLIC})
    if kiosk:
        client.cookies.set(KIOSK_COOKIE, TOKEN)
    return client


@pytest.fixture
def client(hearing: Hearing, devices: FakeDevices, conversations: FakeConversations) -> TestClient:
    return _app(hearing, devices, conversations)


def post(client: TestClient, route: str, body: bytes, kind: str = "audio/wav", **headers: str) -> tuple[int, object]:
    response = client.post(route, content=body, headers={"content-type": kind, **headers})
    return response.status_code, response.json()


def code(body: object) -> str:
    return ErrorResponse.model_validate(body).code


ROUTES = ("/api/chat/transcripts", "/api/kiosk/transcripts")


@pytest.mark.parametrize("route", ROUTES)
def test_a_wav_is_transcribed_as_16k_mono_pcm_and_runs_no_turn(client: TestClient, hearing: Hearing,
                                                               conversations: FakeConversations, route: str) -> None:
    status, body = post(client, route, wav(500))
    assert status == 200 and Transcript.model_validate(body) == Transcript(text=SAID)
    assert hearing.heard == [(AudioFormat(16000, 2, 1), b"\x01\x00" * 8000)]
    assert conversations.calls == [] and hearing.prompts == []


@pytest.mark.parametrize("route", ROUTES)
def test_nothing_said_is_an_empty_transcript(client: TestClient, hearing: Hearing, route: str) -> None:
    hearing.words = ""
    assert post(client, route, wav(300)) == (200, {"text": ""})


def test_no_audio_at_all_is_an_empty_transcript_without_a_call(client: TestClient, hearing: Hearing) -> None:
    assert post(client, ROUTES[0], wav(0)) == (200, {"text": ""})
    assert hearing.heard == []


@pytest.mark.parametrize("route", ROUTES)
def test_a_transcription_that_fails_is_503(client: TestClient, hearing: Hearing, route: str) -> None:
    hearing.error = InferenceUnavailable("no route")
    status, body = post(client, route, wav(300))
    assert status == 503 and code(body) == "unavailable"


@pytest.mark.parametrize("route", ROUTES)
def test_longer_than_the_cap_is_413_and_never_transcribed(client: TestClient, hearing: Hearing, route: str) -> None:
    status, body = post(client, route, wav(1001))
    assert status == 413 and code(body) == "too_large"
    assert post(client, route, wav(1000))[0] == 200
    assert len(hearing.heard) == 1


def test_a_body_over_the_byte_cap_is_413_before_it_is_parsed(client: TestClient, hearing: Hearing) -> None:
    status, body = post(client, ROUTES[0], b"\x00" * (spoken_route.CAPS.max_bytes + 1))
    assert status == 413 and code(body) == "too_large" and hearing.heard == []


@pytest.mark.parametrize("audio", [wav(300, rate=8000), wav(300, channels=2), wav(300, rate=48000), b"RIFF\x00junk",
                                   b"not audio", wav(300)[:-7]])
def test_anything_but_16k_mono_16_bit_pcm_wav_is_415(client: TestClient, hearing: Hearing, audio: bytes) -> None:
    status, body = post(client, ROUTES[0], audio)
    assert status == 415 and code(body) == "unsupported" and hearing.heard == []


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize(("kind", "origin"), [("application/json", PUBLIC), ("multipart/form-data", PUBLIC),
                                              ("text/plain", PUBLIC), ("audio/wav", "https://evil.test")])
def test_a_write_not_from_this_site_as_wav_is_403(hearing: Hearing, devices: FakeDevices,
                                                  conversations: FakeConversations, route: str, kind: str,
                                                  origin: str) -> None:
    client = _app(hearing, devices, conversations, person=False)
    status, body = post(client, route, wav(300), kind=kind, origin=origin)
    assert status == 403 and code(body) == "forbidden" and hearing.heard == []


def test_no_session_is_401(hearing: Hearing, devices: FakeDevices, conversations: FakeConversations) -> None:
    status, body = post(_app(hearing, devices, conversations, person=False), ROUTES[0], wav(300))
    assert status == 401 and code(body) == "unauthorized" and hearing.heard == []


def test_an_unpaired_kiosk_is_401(hearing: Hearing, devices: FakeDevices, conversations: FakeConversations) -> None:
    status, body = post(_app(hearing, devices, conversations, kiosk=False), ROUTES[1], wav(300))
    assert status == 401 and code(body) == "unauthorized" and hearing.heard == []


def test_the_kiosk_through_the_public_tunnel_is_401(client: TestClient, hearing: Hearing) -> None:
    status, body = post(client, ROUTES[1], wav(300), **{"cf-connecting-ip": "203.0.113.9"})
    assert status == 401 and code(body) == "unauthorized" and hearing.heard == []


def test_the_kiosk_counts_a_transcription_against_its_rate(client: TestClient, hearing: Hearing,
                                                           devices: FakeDevices) -> None:
    assert post(client, ROUTES[1], wav(300))[0] == 200
    assert devices.counted == [DEVICE.id]
    devices.over = True
    status, body = post(client, ROUTES[1], wav(300))
    assert status == 429 and code(body) == "rate_limited" and len(hearing.heard) == 1


def test_a_person_is_not_counted_as_a_device(client: TestClient, devices: FakeDevices) -> None:
    assert post(client, ROUTES[0], wav(300))[0] == 200 and devices.counted == []


def test_the_limits_are_served_without_sign_in(hearing: Hearing, devices: FakeDevices,
                                               conversations: FakeConversations) -> None:
    response = _app(hearing, devices, conversations, person=False, kiosk=False).get("/api/spoken/limits")
    voice = voice_config.load().end_of_speech
    assert response.status_code == 200 and SpokenLimits.model_validate(response.json()) == SpokenLimits(
        max_ms=1000, speech_ms=voice.speech_ms, silence_ms=voice.silence_ms, quiet_rms=0.05, voice_s=120)


@pytest.mark.parametrize("route", ROUTES)
def test_the_log_has_sizes_and_never_the_words(client: TestClient, capsys: pytest.CaptureFixture[str],
                                               route: str) -> None:
    capsys.readouterr()
    post(client, route, wav(500))
    out = capsys.readouterr().out
    who = f"person={ALANA.id}" if route == ROUTES[0] else f"device={DEVICE.id}"
    assert f"event=spoken.heard {who} outcome=heard bytes=16044 audio_ms=500" in out
    assert f"chars={len(SAID)}" in out and "zqTURN" not in out


@pytest.mark.parametrize("data", [{}, {"max_ms": 30000}, {"quiet_rms": 0.02}, {"max_ms": 999, "quiet_rms": 0.02, "voice_s": 120},
                                  {"max_ms": "30000", "quiet_rms": 0.02, "voice_s": 120},
                                  {"max_ms": 30000, "quiet_rms": 0.02, "voice_s": 120, "x": 1},
                                  {"max_ms": 30000, "quiet_rms": 0, "voice_s": 120}, {"max_ms": 30000, "quiet_rms": 1, "voice_s": 120},
                                  {"max_ms": 30000, "quiet_rms": "0.02", "voice_s": 120},
                                  {"max_ms": 30000, "quiet_rms": True, "voice_s": 120}, [], None,
                                  {"max_ms": True, "quiet_rms": 0.02, "voice_s": 120}, {"max_ms": 30000, "quiet_rms": 0.02},
                                  {"max_ms": 30000, "quiet_rms": 0.02, "voice_s": 0},
                                  {"max_ms": 30000, "quiet_rms": 0.02, "voice_s": True}])
def test_malformed_caps_are_refused(data: object) -> None:
    with pytest.raises(ValueError):
        spoken.parse(data)


def test_the_shipped_caps_load_and_bound_the_bytes() -> None:
    caps = spoken.load()
    assert caps.max_ms >= 1000
    assert replace(caps, max_ms=1000).max_bytes == 44 + 32000
    assert 0 < caps.quiet_rms < 1
