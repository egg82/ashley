"""`GET /api/chat/turns/{id}/voice` and `GET /api/kiosk/turns/{id}/voice` with fakes behind the locator: the caller's own
thread and household reach the speech of the lexicon-respelled `spoken`, anything else is one 404 whatever the reason,
no credential is 401, an unreachable store or voice is 503, and the `voice.turn` line holds ids and timings only."""

from collections.abc import Generator

import pytest
from ashley import services
from ashley.api.kiosk_device import kiosk_signed_in
from ashley.api.models import ErrorResponse
from ashley.api.person import person_signed_in
from ashley.channels import spoken
from ashley.channels.lexicon import Lexicon
from ashley.channels.lexicons import Lexicons, NullLexicons
from ashley.channels.model import Device
from ashley.conversations.conversations import Conversations, ConversationsUnavailable
from ashley.inference.inference import Inference, InferenceUnavailable
from ashley.inference.speech import Speech, SpeechTask
from ashley.main import create_app
from ashley.settings import Settings
from ashley.signin.model import SignedIn
from contract.conversations_support import events
from fastapi.testclient import TestClient
from respond_support import ALANA, FakeConversations
from voice_support import FakeSpeech

PUBLIC = "https://ashley.test"
DEVICE = Device(7, ALANA.household_id, "hall tablet", "hallway", "present", "text", "chat")
CHAT, KIOSK = f"person:{ALANA.id}:web", f"device:{DEVICE.id}"
VOICES = {(ALANA.household_id, CHAT, 5): "It is noon, Zorp.", (ALANA.household_id, KIOSK, 6): "Hello from the hall."}


class Voices(FakeConversations):
    """Holds a voice per (household, thread, turn) and answers `spoken` as the service does for a turn on that thread."""

    asked: list[tuple[int, str, int, int]] = []
    down: bool = False

    async def spoken(self, household_id: int, thread: str, turn_id: int, within_s: int) -> str | None:
        self.asked.append((household_id, thread, turn_id, within_s))
        if self.down:
            raise ConversationsUnavailable("down")
        return VOICES.get((household_id, thread, turn_id))


class Respelled(NullLexicons):
    async def of(self, household_id: int | None) -> Lexicon:
        return Lexicon({"Zorp": "Zorpe"})


@pytest.fixture
def speech() -> Generator[FakeSpeech]:
    yield FakeSpeech(audio=b"ID3-voice")


@pytest.fixture
def conversations() -> Generator[Voices]:
    got = Voices()
    got.asked = []
    yield got


@pytest.fixture(autouse=True)
def unwired() -> Generator[None]:
    yield
    for service in (Conversations, Inference, Lexicons):
        services.unregister(service)


def app(speech: FakeSpeech, conversations: Voices, person: bool = True, kiosk: bool = True) -> TestClient:
    made = create_app(Settings(database_url="", build_version="test", public_url=PUBLIC))
    services.register(Conversations, conversations)
    services.register(Inference, speech)
    services.register(Lexicons, Respelled())
    if person:
        made.dependency_overrides[person_signed_in] = lambda: SignedIn(1, ALANA)
    if kiosk:
        made.dependency_overrides[kiosk_signed_in] = lambda: DEVICE
    return TestClient(made, base_url=PUBLIC)


def test_a_person_hears_the_respelled_voice_of_their_own_turn(speech: FakeSpeech, conversations: Voices) -> None:
    response = app(speech, conversations).get("/api/chat/turns/5/voice")
    assert response.status_code == 200 and response.content == b"ID3-voice"
    assert speech.spoken == ["It is noon, Zorpe."]
    assert conversations.asked == [(ALANA.household_id, CHAT, 5, spoken.load().voice_s)]


def test_the_media_type_is_the_speechs_own(speech: FakeSpeech, conversations: Voices) -> None:
    class Wav(FakeSpeech):
        async def speak(self, task: SpeechTask, text: str, *, conversation_id: int | None = None) -> Speech:
            made = await super().speak(task, text, conversation_id=conversation_id)
            return Speech("audio/wav", made.chunks, made.provider, made.model)

    response = app(Wav(audio=b"RIFF-voice"), conversations).get("/api/chat/turns/5/voice")
    assert response.status_code == 200 and response.headers["content-type"] == "audio/wav"
    assert app(speech, conversations).get("/api/chat/turns/5/voice").headers["content-type"] == "audio/mpeg"


def test_the_kiosk_hears_its_own_threads_voice(speech: FakeSpeech, conversations: Voices) -> None:
    response = app(speech, conversations).get("/api/kiosk/turns/6/voice")
    assert response.status_code == 200 and response.content == b"ID3-voice"
    assert conversations.asked == [(DEVICE.household_id, KIOSK, 6, spoken.load().voice_s)]


@pytest.mark.parametrize(("path", "turn"), [("/api/chat/turns/%d/voice", 6), ("/api/kiosk/turns/%d/voice", 5),
                                            ("/api/chat/turns/%d/voice", 99)])
def test_a_turn_not_on_the_callers_own_thread_or_with_no_voice_is_one_404(
        speech: FakeSpeech, conversations: Voices, path: str, turn: int) -> None:
    response = app(speech, conversations).get(path % turn)
    assert response.status_code == 404 and ErrorResponse.model_validate(response.json()).code == "not_found"
    assert speech.spoken == [], "nothing was synthesised for a turn that is not theirs"


@pytest.mark.parametrize("path", ["/api/chat/turns/5/voice", "/api/kiosk/turns/6/voice"])
def test_no_credential_is_401_and_reads_nothing(speech: FakeSpeech, conversations: Voices, path: str) -> None:
    response = app(speech, conversations, person=False, kiosk=False).get(path)
    assert response.status_code == 401 and conversations.asked == []


@pytest.mark.parametrize("path", ["/api/chat/turns/abc/voice", "/api/kiosk/turns/1.5/voice"])
def test_a_non_integer_id_is_422(speech: FakeSpeech, conversations: Voices, path: str) -> None:
    assert app(speech, conversations).get(path).status_code == 422 and conversations.asked == []


def test_an_unreachable_store_or_voice_is_503(speech: FakeSpeech, conversations: Voices) -> None:
    conversations.down = True
    assert app(speech, conversations).get("/api/chat/turns/5/voice").status_code == 503
    conversations.down = False
    speech.audio = InferenceUnavailable("no voice")
    got = app(speech, conversations).get("/api/chat/turns/5/voice")
    assert got.status_code == 503 and ErrorResponse.model_validate(got.json()).code == "unavailable"


@pytest.mark.parametrize(("path", "by", "caller"), [("/api/chat/turns/5/voice", "person", ALANA.id),
                                                    ("/api/kiosk/turns/6/voice", "device", DEVICE.id)])
def test_the_log_line_holds_ids_and_timings_and_never_the_words(
        speech: FakeSpeech, conversations: Voices, capsys: pytest.CaptureFixture[str], path: str, by: str,
        caller: int) -> None:
    capsys.readouterr()
    app(speech, conversations).get(path)
    out = capsys.readouterr().out
    (line,) = events(out, "voice.turn")
    assert line["by"] == by and line[by] == str(caller) and line["turn"] == path.split("/")[4]
    assert line["tts_provider"] == "fake" and line["complete"] == "true" and line["bytes"] == "9"
    assert "tts_first_byte_ms" in line and "noon" not in out and "Zorp" not in out and "Hello" not in out
