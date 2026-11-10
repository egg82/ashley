"""`voice.later`: a reply said to `device:<id>` is stored as a clip and its URL played on the satellite's room speaker
when it names one and the player accepts, else announced on the satellite itself; a thread that is no connected
satellite, or not `device:<digits>`, is dropped; clips down plays nothing; `voice.later` logs the outcome. `drain` takes
`device:` every poll and says each reply, logging `voice.outbox_unavailable` once per run of failures."""

import pytest
from ashley.channels.model import Device, Satellite
from ashley.channels.outbox import Later
from ashley.channels.voice.clips import ClipsUnavailable
from ashley.channels.voice.connection import Announcer
from ashley.channels.voice.later import drain, say
from ashley.channels.voice.run import Pipeline
from contract.conversations_support import run
from later_support import FakeClips, FakeOutbox, Logged, Polls, clips as clips, drained, outbox as outbox, unavailable
from later_support import waiting
from voice_support import FakeConnection, FakeSpeaker, FakeTurnLoop, pipeline

MARK = "zqLEAK9035"
URL = "https://ashley.test/api/voice/clips/tok-1"


def satellite(device_id: int = 3, room_speaker: str | None = None) -> Satellite:
    return Satellite(Device(device_id, 1, f"echo {device_id}", "office", "present", "spoken", "command"), "10.0.0.9",
                     room_speaker)


Links = dict[int, tuple[Satellite, Announcer]]


def links_of(*pairs: tuple[Satellite, FakeConnection]) -> Links:
    return {s.device.id: (s, c) for s, c in pairs}


def said(later: Later, links: Links, pipe: Pipeline) -> None:
    async def scenario() -> None:
        await say(later, links, pipe)

    run(scenario())


def reply(thread: str = "device:3", body: str = "It is noon.", age_ms: int = 2500) -> Later:
    return waiting(thread, body, age_ms=age_ms)


def test_without_a_room_speaker_the_clip_url_is_announced_on_the_satellite(clips: FakeClips) -> None:
    conn, speaker = FakeConnection(), FakeSpeaker()
    said(reply(), links_of((satellite(), conn)), pipeline(FakeTurnLoop(), speaker))
    assert clips.added == [(3, "It is noon.", 2500)]
    assert conn.announced == [URL] and speaker.played == []


def test_with_a_room_speaker_that_accepts_the_clip_is_played_there_and_not_announced(clips: FakeClips) -> None:
    conn, speaker = FakeConnection(), FakeSpeaker(accepts=True)
    said(reply(), links_of((satellite(room_speaker="media_player.kitchen"), conn)), pipeline(FakeTurnLoop(), speaker))
    assert speaker.played == [("media_player.kitchen", URL)] and speaker.households == [1]
    assert conn.announced == []


def test_with_a_room_speaker_but_no_player_it_is_announced(clips: FakeClips) -> None:
    conn = FakeConnection()
    said(reply(), links_of((satellite(room_speaker="media_player.kitchen"), conn)), pipeline(FakeTurnLoop(), None))
    assert conn.announced == [URL]


def test_a_player_that_refuses_falls_back_to_the_announcement(clips: FakeClips) -> None:
    conn, speaker = FakeConnection(), FakeSpeaker(accepts=False)
    said(reply(), links_of((satellite(room_speaker="media_player.kitchen"), conn)), pipeline(FakeTurnLoop(), speaker))
    assert speaker.played == [("media_player.kitchen", URL)]
    assert conn.announced == [URL]


def test_the_reply_goes_to_the_satellite_it_names_and_no_other(clips: FakeClips) -> None:
    three, four = FakeConnection(), FakeConnection()
    said(reply("device:4"), links_of((satellite(3), three), (satellite(4), four)), pipeline(FakeTurnLoop()))
    assert four.announced == [URL] and three.announced == []
    assert clips.added[0][0] == 4


@pytest.mark.parametrize("thread", [
    "device:7:kitchen", "device:", "device:x", "device:3x", "discord:3", "device:3:", "device: 3", "device:-3", "3"])
def test_a_thread_that_is_not_device_digits_is_dropped(clips: FakeClips, thread: str) -> None:
    conn, speaker = FakeConnection(), FakeSpeaker()
    said(reply(thread), links_of((satellite(3), conn), (satellite(7), conn)), pipeline(FakeTurnLoop(), speaker))
    assert clips.added == [] and conn.announced == [] and speaker.played == []


def test_a_thread_that_names_no_connected_satellite_is_dropped_and_logged(
        clips: FakeClips, capsys: pytest.CaptureFixture[str]) -> None:
    conn, speaker = FakeConnection(), FakeSpeaker()
    log = Logged(capsys)
    said(reply("device:9"), links_of((satellite(3), conn)), pipeline(FakeTurnLoop(), speaker))
    assert clips.added == [] and conn.announced == [] and speaker.played == []
    (line,) = log.events("voice.later")
    assert line["outcome"] == "not_connected"


def test_clips_unavailable_plays_nothing_and_is_logged(clips: FakeClips, capsys: pytest.CaptureFixture[str]) -> None:
    clips.error = ClipsUnavailable("down")
    conn, speaker = FakeConnection(), FakeSpeaker()
    log = Logged(capsys)
    said(reply(), links_of((satellite(room_speaker="media_player.kitchen"), conn)), pipeline(FakeTurnLoop(), speaker))
    assert conn.announced == [] and speaker.played == []
    (line,) = log.events("voice.later")
    assert line["outcome"] == "clips_unavailable"


def test_a_satellite_with_no_media_player_is_logged_as_such(clips: FakeClips, capsys: pytest.CaptureFixture[str]) -> None:
    conn = FakeConnection(has_player=False)
    log = Logged(capsys)
    said(reply(), links_of((satellite(), conn)), pipeline(FakeTurnLoop()))
    (line,) = log.events("voice.later")
    assert line["outcome"] == "no_media_player" and conn.announced == []


@pytest.mark.parametrize(("room", "accepts", "outcome"), [(None, True, "announced"),
                                                          ("media_player.kitchen", True, "room_speaker"),
                                                          ("media_player.kitchen", False, "announced")])
def test_the_outcome_names_where_it_played(clips: FakeClips, capsys: pytest.CaptureFixture[str], room: str | None,
                                           accepts: bool, outcome: str) -> None:
    log = Logged(capsys)
    said(reply(), links_of((satellite(room_speaker=room), FakeConnection())),
         pipeline(FakeTurnLoop(), FakeSpeaker(accepts=accepts)))
    (line,) = log.events("voice.later")
    assert line["outcome"] == outcome
    assert "3" in line.values(), "the device"
    assert line["age_ms"] == "2500"
    assert "1" in line.values(), "the clip id"


def test_the_log_carries_neither_the_words_nor_the_clip_token(clips: FakeClips,
                                                              capsys: pytest.CaptureFixture[str]) -> None:
    log = Logged(capsys)
    said(reply(body=MARK), links_of((satellite(), FakeConnection())), pipeline(FakeTurnLoop()))
    assert log.events("voice.later")
    assert MARK not in log.read() and "tok-1" not in log.read()


def test_drain_takes_the_device_threads_each_poll_and_says_each_reply(clips: FakeClips, outbox: FakeOutbox) -> None:
    conn = FakeConnection()
    outbox.waiting = [waiting("device:3", "one", id_=1), waiting("device:3", "two", id_=2),
                      waiting("discord:5", "elsewhere", id_=3)]
    polls = Polls(stop_at=3)

    async def scenario() -> None:
        await drained(drain(links_of((satellite(), conn)), pipeline(FakeTurnLoop()), 0.25, polls))

    run(scenario())
    assert [b for _, b, _ in clips.added] == ["one", "two"]
    assert conn.announced == ["https://ashley.test/api/voice/clips/tok-1", "https://ashley.test/api/voice/clips/tok-2"]
    assert set(outbox.prefixes) == {"device:"} and len(outbox.prefixes) >= 2
    assert polls.waits == [0.25] * 3
    assert [w.thread for w in outbox.waiting] == ["discord:5"]


def test_a_run_of_outbox_failures_is_logged_once_and_the_drain_keeps_going(
        clips: FakeClips, outbox: FakeOutbox, capsys: pytest.CaptureFixture[str]) -> None:
    conn = FakeConnection()
    outbox.take_errors = [unavailable(), unavailable(), None, unavailable(), None, None]
    outbox.waiting = [waiting("device:3", "after", id_=1)]
    log = Logged(capsys)
    polls = Polls(stop_at=6)

    async def scenario() -> None:
        await drained(drain(links_of((satellite(), conn)), pipeline(FakeTurnLoop()), 0.01, polls))

    run(scenario())
    assert len(log.events("voice.outbox_unavailable")) == 2, "one line per run of failures, two runs"
    assert conn.announced == ["https://ashley.test/api/voice/clips/tok-1"]
