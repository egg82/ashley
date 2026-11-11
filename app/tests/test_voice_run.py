"""One wake, carried through `Run` against a fake device link, fake speech and turn loop, and real clips in Postgres:
the events in Home Assistant's order, end of speech by the VAD, the Inbound she is asked, the clip stored before its
URL is sent, the room speaker, every failure ending the run, and the `voice.run` line."""

import asyncio
import hashlib
from collections.abc import Generator

import pytest
from aioesphomeapi.model import VoiceAssistantEventType as Event
from ashley import logs, services
from ashley.channels.model import Inbound, Outbound, Satellite
from ashley.channels.respond import RespondRefused, RespondUnavailable
from ashley.channels.voice.clips import Clips
from ashley.channels.voice.postgres_clips import PostgresClips
from ashley.channels.voice.run import Run
from ashley.db.pool import PoolDatabase
from ashley.live.events import HerState
from ashley.live.live import Live
from ashley.inference.inference import Inference, InferenceUnavailable
from contract.conversations_support import db_url as db_url, events, household
from language_support import unwire, wire
from live_support import FakeLive
from contract.conversations_support import migrated_template as migrated_template, scalar
from voice_support import FRAME, QUIET, SPEECH, FakeLink, FakeSpeaker, FakeSpeech, FakeTurnLoop, pipeline
from voice_support import satellite_row

E = Event
HEARD = [E.VOICE_ASSISTANT_RUN_START, E.VOICE_ASSISTANT_STT_START, E.VOICE_ASSISTANT_STT_VAD_START,
         E.VOICE_ASSISTANT_STT_VAD_END]
ANSWERED = [*HEARD, E.VOICE_ASSISTANT_STT_END, E.VOICE_ASSISTANT_INTENT_START, E.VOICE_ASSISTANT_INTENT_END]


@pytest.fixture(autouse=True)
def speech_unwired() -> Generator[None]:
    yield
    services.unregister(Inference)
    services.unregister(Clips)
    unwire()


def carry(url: str, satellite: Satellite, speech: FakeSpeech, loop: FakeTurnLoop, speaker: FakeSpeaker | None = None,
          frames: int = 20, probabilities: list[float] | None = None, playing_s: float = 0) -> FakeLink:
    """One run: `frames` frames of microphone audio, then the device's end of audio."""
    link = FakeLink()
    services.register(Inference, speech)

    async def scenario() -> None:
        database = PoolDatabase(url)
        await database.open()
        services.register(Clips, PostgresClips(database, 120))
        try:
            run = Run(satellite, link, pipeline(loop, speaker, probabilities))
            for _ in range(frames):
                run.audio(FRAME)
            run.end_audio()
            await asyncio.wait_for(run.go(), 5)
            await asyncio.sleep(playing_s)
        finally:
            await database.close()

    asyncio.run(scenario())
    return link


def clip_url_token(link: FakeLink) -> str:
    data = link.data(E.VOICE_ASSISTANT_TTS_END)
    assert data is not None
    prefix = "https://ashley.test/api/voice/clips/"
    assert data["url"].startswith(prefix)
    return data["url"][len(prefix):]


def test_a_wake_is_answered_in_home_assistants_event_order(db_url: str) -> None:
    satellite = satellite_row(db_url, household(db_url))
    speech, loop = FakeSpeech(), FakeTurnLoop(body="Mowchi is asleep.")
    link = carry(db_url, satellite, speech, loop)
    assert link.kinds() == [*ANSWERED, E.VOICE_ASSISTANT_TTS_START, E.VOICE_ASSISTANT_TTS_END,
                            E.VOICE_ASSISTANT_RUN_END]
    assert link.data(E.VOICE_ASSISTANT_STT_END) == {"text": "what time is it"}
    assert link.data(E.VOICE_ASSISTANT_INTENT_END) == {"conversation_id": "41", "continue_conversation": "0"}
    assert link.data(E.VOICE_ASSISTANT_TTS_START) == {"text": "Mowchi is asleep."}
    token = clip_url_token(link)
    stored = scalar(db_url, "SELECT body FROM voice_clips WHERE token_sha256 = %s AND device_id = %s",
                    (hashlib.sha256(token.encode()).digest(), satellite.device.id))
    assert stored == "Mowchi is asleep."


def test_the_transcript_is_asked_for_in_the_language_of_the_devices_household(db_url: str) -> None:
    home = household(db_url)
    wire(home, "de-DE")
    speech = FakeSpeech()
    carry(db_url, satellite_row(db_url, home), speech, FakeTurnLoop())
    assert speech.languages == ["de"]


def test_a_household_that_cannot_say_leaves_the_language_to_the_route(db_url: str) -> None:
    speech = FakeSpeech()
    carry(db_url, satellite_row(db_url, household(db_url)), speech, FakeTurnLoop())
    assert speech.languages == [None]


def test_she_is_asked_on_the_devices_thread_as_a_shared_spoken_channel(db_url: str) -> None:
    satellite = satellite_row(db_url, household(db_url))
    loop = FakeTurnLoop()
    carry(db_url, satellite, FakeSpeech(transcript="turn the lights off"), loop)
    [inbound] = loop.asked
    device = satellite.device
    assert (inbound.household_id, inbound.thread, inbound.text, inbound.kind, inbound.medium, inbound.audience,
            inbound.speaker_id, inbound.shared, inbound.place) == (
        device.household_id, f"device:{device.id}", "turn the lights off", "command", "spoken", "present", None, True,
        "office")


def test_her_inbound_is_one_whose_replies_may_come_later(db_url: str) -> None:
    satellite = satellite_row(db_url, household(db_url))
    loop = FakeTurnLoop()
    carry(db_url, satellite, FakeSpeech(), loop)
    [inbound] = loop.asked
    assert inbound.later is True


def test_her_inbound_arrived_by_voice(db_url: str) -> None:
    satellite = satellite_row(db_url, household(db_url))
    loop = FakeTurnLoop()
    carry(db_url, satellite, FakeSpeech(), loop)
    [inbound] = loop.asked
    assert inbound.channel == "voice"


def test_transcription_hears_up_to_the_end_of_speech_and_no_further(db_url: str) -> None:
    satellite = satellite_row(db_url, household(db_url))
    speech = FakeSpeech()
    link = carry(db_url, satellite, speech, FakeTurnLoop(), frames=30, probabilities=[SPEECH] * 3)
    # 3 frames of speech start it, 5 quiet frames end it: the 8th chunk is the last one read
    assert len(speech.heard) == 8
    assert link.kinds().count(E.VOICE_ASSISTANT_STT_VAD_END) == 1


def test_no_speech_until_the_maximum_turns_the_mic_off_without_claiming_speech_started(db_url: str) -> None:
    satellite = satellite_row(db_url, household(db_url))
    speech = FakeSpeech(transcript="")
    link = carry(db_url, satellite, speech, FakeTurnLoop(), frames=250, probabilities=[QUIET] * 250)
    assert len(speech.heard) == 200, "the 2000 ms maximum ends it"
    assert link.kinds() == [E.VOICE_ASSISTANT_RUN_START, E.VOICE_ASSISTANT_STT_START, E.VOICE_ASSISTANT_STT_VAD_END,
                            E.VOICE_ASSISTANT_RUN_END]


def test_audio_that_ends_first_ends_the_utterance_without_a_vad_end(db_url: str) -> None:
    satellite = satellite_row(db_url, household(db_url))
    speech = FakeSpeech()
    link = carry(db_url, satellite, speech, FakeTurnLoop(), frames=4, probabilities=[QUIET] * 4)
    assert len(speech.heard) == 4
    assert E.VOICE_ASSISTANT_STT_VAD_START not in link.kinds() and E.VOICE_ASSISTANT_STT_VAD_END not in link.kinds()
    assert E.VOICE_ASSISTANT_STT_END in link.kinds()


def test_an_empty_transcript_ends_the_run_quietly(db_url: str) -> None:
    satellite = satellite_row(db_url, household(db_url))
    loop = FakeTurnLoop()
    link = carry(db_url, satellite, FakeSpeech(transcript=""), loop)
    assert link.kinds() == [*HEARD, E.VOICE_ASSISTANT_RUN_END]
    assert loop.asked == [] and scalar(db_url, "SELECT count(*) FROM voice_clips") == 0


@pytest.mark.parametrize(("speech", "loop", "code", "reason"), [
    (FakeSpeech(transcript=InferenceUnavailable("down")), FakeTurnLoop(), "stt-provider-unavailable",
     "stt_unavailable"),
    (FakeSpeech(), FakeTurnLoop(error=RespondRefused()), "intent-failed", "refused"),
    (FakeSpeech(), FakeTurnLoop(error=RespondUnavailable()), "intent-failed", "respond_unavailable"),
])
def test_a_failure_ends_the_run_with_the_devices_error_event(db_url: str, capsys: pytest.CaptureFixture[str],
                                                            speech: FakeSpeech, loop: FakeTurnLoop, code: str,
                                                            reason: str) -> None:
    logs.setup()
    satellite = satellite_row(db_url, household(db_url))
    link = carry(db_url, satellite, speech, loop)
    assert link.kinds()[-2:] == [E.VOICE_ASSISTANT_ERROR, E.VOICE_ASSISTANT_RUN_END]
    error = link.data(E.VOICE_ASSISTANT_ERROR)
    assert error is not None and error["code"] == code and error["message"]
    assert E.VOICE_ASSISTANT_TTS_END not in link.kinds()
    assert [e["outcome"] for e in events(capsys.readouterr().out, "voice.run")] == [reason]


def test_unstorable_clips_end_the_run_with_tts_failed(db_url: str) -> None:
    satellite = satellite_row(db_url, household(db_url))
    link = FakeLink()
    services.register(Inference, FakeSpeech())
    run = Run(satellite, link, pipeline(FakeTurnLoop()))   # Clips unwired: its Null Object raises
    for _ in range(10):
        run.audio(FRAME)
    run.end_audio()
    asyncio.run(run.go())
    assert link.kinds()[-2:] == [E.VOICE_ASSISTANT_ERROR, E.VOICE_ASSISTANT_RUN_END]
    assert link.data(E.VOICE_ASSISTANT_ERROR) == {"code": "tts-failed", "message": "Her reply could not be prepared"}


def test_a_room_speaker_plays_the_clip_and_the_device_plays_nothing(db_url: str) -> None:
    satellite = satellite_row(db_url, household(db_url), room_speaker="media_player.office")
    speaker = FakeSpeaker()
    link = carry(db_url, satellite, FakeSpeech(), FakeTurnLoop(), speaker)
    assert link.kinds() == [*ANSWERED, E.VOICE_ASSISTANT_RUN_END]
    [(entity, url)] = speaker.played
    assert entity == "media_player.office" and url.startswith("https://ashley.test/api/voice/clips/")
    assert speaker.households == [satellite.device.household_id]
    assert scalar(db_url, "SELECT count(*) FROM voice_clips") == 1


def test_a_room_speaker_that_refuses_falls_back_to_the_device(db_url: str) -> None:
    satellite = satellite_row(db_url, household(db_url), room_speaker="media_player.office")
    speaker = FakeSpeaker(accepts=False)
    link = carry(db_url, satellite, FakeSpeech(), FakeTurnLoop(), speaker)
    assert link.kinds()[-3:] == [E.VOICE_ASSISTANT_TTS_START, E.VOICE_ASSISTANT_TTS_END, E.VOICE_ASSISTANT_RUN_END]
    assert speaker.played[0][1] == f"https://ashley.test/api/voice/clips/{clip_url_token(link)}"


def test_the_run_line_carries_ids_and_durations_never_words(db_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    satellite = satellite_row(db_url, household(db_url))
    link = carry(db_url, satellite, FakeSpeech(transcript="secret question"), FakeTurnLoop(body="secret answer"))
    out = capsys.readouterr().out
    [line] = events(out, "voice.run")
    assert line["device"] == str(satellite.device.id) and line["outcome"] == "ok"
    assert line["clip"] == str(scalar(db_url, "SELECT id FROM voice_clips"))
    assert {"wake_to_stt_end_ms", "stt_ms", "respond_ms"} <= set(line)
    assert all(line[k].isdigit() for k in ("wake_to_stt_end_ms", "stt_ms", "respond_ms"))
    assert "secret" not in out and clip_url_token(link) not in out


def test_a_heard_question_warms_her_voice_once(db_url: str) -> None:
    speech = FakeSpeech()
    carry(db_url, satellite_row(db_url, household(db_url)), speech, FakeTurnLoop())
    assert speech.warmed == ["speak"]


def test_the_voice_is_warmed_by_the_time_the_reply_has_been_made(db_url: str) -> None:
    speech = FakeSpeech()
    seen: list[list[str]] = []

    class Watching(FakeTurnLoop):
        async def __call__(self, inbound: Inbound) -> Outbound:
            await asyncio.sleep(0.01)
            seen.append(list(speech.warmed))
            return await super().__call__(inbound)

    carry(db_url, satellite_row(db_url, household(db_url)), speech, Watching())
    assert seen == [["speak"]]


def test_an_empty_transcript_does_not_warm_her_voice(db_url: str) -> None:
    speech = FakeSpeech(transcript="")
    carry(db_url, satellite_row(db_url, household(db_url)), speech, FakeTurnLoop())
    assert speech.warmed == []


def test_unavailable_transcription_does_not_warm_her_voice(db_url: str) -> None:
    speech = FakeSpeech(transcript=InferenceUnavailable("down"))
    carry(db_url, satellite_row(db_url, household(db_url)), speech, FakeTurnLoop())
    assert speech.warmed == []


def test_the_run_line_names_the_route_that_transcribed(db_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    carry(db_url, satellite_row(db_url, household(db_url)), FakeSpeech(), FakeTurnLoop())
    [line] = events(capsys.readouterr().out, "voice.run")
    assert (line["stt_provider"], line["stt_model"]) == ("fake", "fake-stt")


def test_the_run_line_has_no_stt_route_when_transcription_was_unavailable(
        db_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    carry(db_url, satellite_row(db_url, household(db_url)), FakeSpeech(transcript=InferenceUnavailable("down")),
          FakeTurnLoop())
    [line] = events(capsys.readouterr().out, "voice.run")
    assert line["outcome"] == "stt_unavailable"
    assert "stt_provider" not in line and "stt_model" not in line


def test_a_cancelled_run_logs_aborted(db_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    satellite = satellite_row(db_url, household(db_url))
    services.register(Inference, FakeSpeech())

    async def scenario() -> None:
        task = asyncio.create_task(Run(satellite, FakeLink(), pipeline(FakeTurnLoop())).go())
        await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    assert [e["outcome"] for e in events(capsys.readouterr().out, "voice.run")] == ["aborted"]


def states_of(live: FakeLive) -> list[str]:
    return [e.state for e in live.published if isinstance(e, HerState)]


@pytest.fixture
def live() -> Generator[FakeLive]:
    made = FakeLive()
    services.register(Live, made)
    yield made
    services.unregister(Live)


def test_the_household_is_shown_her_listening_then_speaking_then_idle(db_url: str, live: FakeLive) -> None:
    satellite = satellite_row(db_url, household(db_url))
    carry(db_url, satellite, FakeSpeech(), FakeTurnLoop(body="Mowchi is asleep."), playing_s=0.05)
    assert states_of(live) == ["listening", "idle", "speaking", "idle"]
    states = [e for e in live.published if isinstance(e, HerState)]
    assert {e.turn for e in states} == {states[0].turn}
    assert {(e.shown.household_id, e.shown.person_id, e.shown.device_id) for e in states} == {
        (satellite.device.household_id, None, None)}


def test_a_room_speaker_reply_is_shown_speaking_too(db_url: str, live: FakeLive) -> None:
    satellite = satellite_row(db_url, household(db_url), room_speaker="media_player.office")
    carry(db_url, satellite, FakeSpeech(), FakeTurnLoop(), FakeSpeaker(), playing_s=0.05)
    assert states_of(live) == ["listening", "idle", "speaking", "idle"]


def test_a_run_that_fails_never_shows_her_speaking(db_url: str, live: FakeLive) -> None:
    satellite = satellite_row(db_url, household(db_url))
    carry(db_url, satellite, FakeSpeech(), FakeTurnLoop(error=RespondUnavailable()), playing_s=0.05)
    assert states_of(live) == ["listening", "idle"]


def test_an_unwired_live_changes_nothing_about_the_run(db_url: str) -> None:
    satellite = satellite_row(db_url, household(db_url))
    link = carry(db_url, satellite, FakeSpeech(), FakeTurnLoop(body="Mowchi is asleep."), playing_s=0.05)
    assert link.kinds()[-1] == E.VOICE_ASSISTANT_RUN_END
