"""The Media port (`ashley.runs.media`): a service behind the locator whose Null Object does neither job, so her tools
for them are not offered; `MediaUnavailable` carries the short reason; the records are what a job is given and brings back."""

import pytest
from ashley import services
from ashley.runs.captions import Segment
from ashley.runs.media import Media, MediaUnavailable, NullMedia, Sheet, Source, Transcribed
from ashley.tools.bench_tools import BenchTools
from bench_media_blind_support import MP3, MP4, call, go, scene, sha

SOURCE = Source(1, "a" * 64, 100, "video/mp4")


def test_unwired_the_locator_answers_the_null_object_that_can_do_nothing() -> None:
    services.unregister(Media)
    got = services.get(Media)
    assert isinstance(got, NullMedia) and got.available() is False
    assert Media.null().available() is False


def test_the_null_object_does_neither_job_and_says_why() -> None:
    async def scenario() -> None:
        null = NullMedia()
        with pytest.raises(MediaUnavailable):
            await null.frames("media-x", SOURCE, (1.0,))
        with pytest.raises(MediaUnavailable):
            await null.transcribe("media-x", SOURCE, None)

    go(scenario())


def test_an_unavailable_job_carries_its_reason() -> None:
    err = MediaUnavailable("no_audio")
    assert isinstance(err, Exception) and err.reason == "no_audio"
    assert "no_audio" in str(err)


def test_the_records_hold_what_they_are_given() -> None:
    assert (SOURCE.household_id, SOURCE.sha256, SOURCE.size, SOURCE.media_type) == (1, "a" * 64, 100, "video/mp4")
    assert Sheet(b"j", 2, 9.5) == Sheet(b"j", 2, 9.5) and Sheet(b"j", 2, 9.5) != Sheet(b"j", 3, 9.5)
    t = Transcribed("captions", 12.0, (Segment(1, "x"),))
    assert (t.source, t.duration_s, t.segments) == ("captions", 12.0, (Segment(1, "x"),))
    assert Source(1, "a" * 64, 100, "video/mp4") == SOURCE


def test_a_wired_worker_is_what_the_locator_gives(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            assert services.get(Media) is s.media and s.media.available()

    go(scenario())


def test_a_worker_that_fails_leaves_no_recording_changed(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            clip = await s.put(MP4, "v.mp4")
            audio = await s.put(MP3, "a.mp3")
            s.media.words_to_give = MediaUnavailable("timed_out")
            before = await s.pieces()
            await s.tools().call(call("bench_transcribe", piece_id=clip.id))
            await s.tools().call(call("bench_transcribe", piece_id=audio.id))
            assert await s.pieces() == before and len(s.media.transcribe_jobs) == 2

    go(scenario())


def test_the_bench_reads_a_recording_by_name_size_and_type_never_its_hash(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            clip = await s.put(MP4, "holiday.mp4")
            tools = BenchTools(s.alana.household_id, s.alana.person_id, s.bench)
            for name, args in (("bench_read", {}), ("bench_read_piece", {"piece_id": clip.id})):
                got = await tools.call(call(name, **args))
                assert not got.is_error and "holiday.mp4" in got.content and "video/mp4" in got.content
                assert sha(MP4) not in got.content

    go(scenario())
