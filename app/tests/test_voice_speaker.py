"""The voice's speaker step inside one `Run`: the voiceprint of the utterance (and nothing after it) made while
transcription finishes, an armed device enrolling, a match naming the person only when the policy decides, every
failure leaving the speaker unknown with the wake still answered, and the `voice.speaker` line; then how the turn
loop's speaker step weighs `heard_as`."""

import asyncio
import dataclasses
from collections.abc import Generator
from dataclasses import dataclass, field
from datetime import datetime

import pytest
from aioesphomeapi.model import VoiceAssistantEventType as Event
from ashley import logs, services
from ashley.channels.model import Device, Satellite
from ashley.channels.speaker import who
from ashley.channels.voice.heard_as import MatchPolicy
from ashley.channels.voice.run import Run
from ashley.channels.voice.voices import Enrolled, PersonPrints, Voices, VoicesUnavailable
from ashley.inference.inference import Inference, InferenceUnavailable
from ashley.inference.speech import AudioFormat, Heard, SpeechTask, Transcript
from ashley.inference.voiceprint import Voiceprint
from ashley.senses.presence import Presence
from contract.conversations_support import events
from respond_support import ALANA, SAM, Fakes, inbound, wired as wired
from voice_support import FRAME, LOGS_ONLY, FakeLink, FakeSpeech, FakeTurnLoop, pipeline

DECIDES = dataclasses.replace(LOGS_ONLY, decides=True)
DEVICE = Device(7, 10, "office echo", "office", "present", "spoken", "command")
SATELLITE = Satellite(DEVICE, "10.0.0.9", None)
PERSON = 31


@dataclass
class Printing(FakeSpeech):
    """Also makes voiceprints of (1, 0), or raises `print_error`; records the PCM it was given and whether it was
    called before the transcript was returned."""

    print_error: Exception | None = None
    printed: list[bytes] = field(default_factory=list[bytes])
    printed_before_transcript: bool = False

    async def transcribe(self, task: SpeechTask, heard: Heard, *, conversation_id: int | None = None) -> Transcript:
        transcript = await super().transcribe(task, heard)
        for _ in range(5):
            await asyncio.sleep(0)
        self.printed_before_transcript = bool(self.printed)
        return transcript

    async def voiceprint(self, format: AudioFormat, pcm: bytes, *, conversation_id: int | None = None) -> Voiceprint:
        self.printed.append(pcm)
        if self.print_error is not None:
            raise self.print_error
        return Voiceprint((1.0, 0.0), "titanet", format.duration_ms(len(pcm)))


@dataclass
class FakeVoices(Voices):
    """Holds `people`'s prints, or raises `error`; `armed` is how many wakes enrol `PERSON` (0: not armed)."""

    people: tuple[PersonPrints, ...] = (PersonPrints(PERSON, ((1.0, 0.0),)), PersonPrints(32, ((0.0, 1.0),)))
    armed: int = 0
    error: Exception | None = None
    enrolled: list[Voiceprint] = field(default_factory=list[Voiceprint])

    async def prints(self, household_id: int, model: str) -> tuple[PersonPrints, ...]:
        if self.error is not None:
            raise self.error
        return self.people if model == "titanet" else ()

    async def arm(self, device_id: int, person_id: int, wakes: int, until: datetime) -> None:
        raise AssertionError("not used")

    async def enrol(self, device_id: int, voiceprint: Voiceprint) -> Enrolled | None:
        if self.error is not None:
            raise self.error
        if not self.armed:
            return None
        self.armed -= 1
        self.enrolled.append(voiceprint)
        return Enrolled(PERSON, self.armed)

    async def forget(self, person_id: int) -> int:
        raise AssertionError("not used")


@dataclass
class Home(Presence):
    people: frozenset[int] | None = None

    async def home(self, household_id: int) -> frozenset[int] | None:
        return self.people


@pytest.fixture(autouse=True)
def unwired() -> Generator[None]:
    yield
    for interface in (Inference, Voices, Presence):
        services.unregister(interface)


def wake(speech: Printing, voices: FakeVoices, policy: MatchPolicy = DECIDES, home: frozenset[int] | None = None,
         frames: int = 20) -> tuple[FakeTurnLoop, FakeLink]:
    """One run to the turn loop; the clip store is unwired, so it ends at `tts-failed` after she is asked."""
    services.register(Inference, speech)
    services.register(Voices, voices)
    services.register(Presence, Home(home))
    loop, link = FakeTurnLoop(), FakeLink()

    async def scenario() -> None:
        run = Run(SATELLITE, link, pipeline(loop, policy=policy))
        for _ in range(frames):
            run.audio(FRAME)
        run.end_audio()
        await asyncio.wait_for(run.go(), 5)

    asyncio.run(scenario())
    return loop, link


def speaker_line(capsys: pytest.CaptureFixture[str]) -> dict[str, str]:
    [line] = events(capsys.readouterr().out, "voice.speaker")
    return line


def test_a_match_names_the_person_and_the_line_does_not(capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    speech = Printing()
    loop, _ = wake(speech, FakeVoices(), home=frozenset({PERSON}))
    assert loop.asked[0].heard_as == PERSON and loop.asked[0].speaker_id is None
    line = speaker_line(capsys)
    assert {k: line[k] for k in ("device", "outcome", "best", "second", "people", "presence", "decides")} == {
        "device": "7", "outcome": "matched", "best": "1.00", "second": "0.00", "people": "2", "presence": "yes",
        "decides": "true"}
    assert line["voiceprint_ms"].isdigit() and "remaining" not in line
    assert str(PERSON) not in " ".join(v for k, v in line.items() if k != "ts")


def test_the_print_is_of_the_utterance_only_and_made_while_transcription_finishes() -> None:
    speech = Printing()
    wake(speech, FakeVoices(), frames=30)
    # 3 frames of speech start it, 5 quiet frames end it, as transcription hears it
    assert speech.printed == [FRAME * 8] and speech.heard == [FRAME] * 8
    assert speech.printed_before_transcript


def test_until_the_policy_decides_a_match_is_only_logged(capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    loop, _ = wake(Printing(), FakeVoices(), policy=LOGS_ONLY)
    assert loop.asked[0].heard_as is None
    line = speaker_line(capsys)
    assert (line["outcome"], line["presence"], line["decides"]) == ("matched", "unknown", "false")


def test_an_armed_device_enrols_and_names_no_one(capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    voices = FakeVoices(armed=2)
    loop, _ = wake(Printing(), voices, home=frozenset({PERSON}))
    assert loop.asked[0].heard_as is None and len(voices.enrolled) == 1
    line = speaker_line(capsys)
    assert (line["outcome"], line["remaining"]) == ("enrolled", "1")
    assert "best" not in line and "presence" not in line


def test_a_wake_too_short_to_match_is_not_enrolled(capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    voices = FakeVoices(armed=2)
    short = dataclasses.replace(DECIDES, min_audio_ms=1000)
    loop, _ = wake(Printing(), voices, policy=short)
    assert loop.asked[0].heard_as is None and voices.enrolled == []
    assert speaker_line(capsys)["outcome"] == "too_short"


@pytest.mark.parametrize(("speech", "voices", "outcome"), [
    (Printing(print_error=InferenceUnavailable("down")), FakeVoices(), "unavailable"),
    (Printing(), FakeVoices(error=VoicesUnavailable("down")), "unavailable"),
    (Printing(print_error=TimeoutError()), FakeVoices(), "unavailable"),
    (Printing(print_error=RuntimeError("bug")), FakeVoices(), "error"),
])
def test_a_failure_names_no_one_and_the_wake_is_still_answered(capsys: pytest.CaptureFixture[str], speech: Printing,
                                                              voices: FakeVoices, outcome: str) -> None:
    logs.setup()
    loop, link = wake(speech, voices)
    assert len(loop.asked) == 1 and loop.asked[0].heard_as is None
    assert Event.VOICE_ASSISTANT_INTENT_END in link.kinds()
    out = capsys.readouterr().out
    [line] = events(out, "voice.speaker")
    assert line["outcome"] == outcome
    assert len(events(out, "voice.speaker_error")) == (outcome == "error")


def test_an_empty_transcript_asks_no_one_whose_voice_it_was(capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    voices = FakeVoices(armed=1)
    wake(Printing(transcript=""), voices)
    assert voices.enrolled == [] and events(capsys.readouterr().out, "voice.speaker") == []


def test_the_speaker_is_the_channels_then_the_voices_then_the_one_person_home(wired: Fakes) -> None:
    wired.presence.answer = frozenset({SAM.id})
    heard = dataclasses.replace(inbound(), heard_as=ALANA.id)
    assert asyncio.run(who(heard)).speaker == ALANA
    assert asyncio.run(who(dataclasses.replace(heard, speaker_id=SAM.id))).speaker == SAM
    assert asyncio.run(who(inbound())).speaker == SAM, "control: presence alone names Sam"
    with pytest.raises(ValueError):
        asyncio.run(who(dataclasses.replace(heard, heard_as=999)))
