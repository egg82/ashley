"""`bench_transcribe` writes a reader body that names the recording and one start per non-empty line, and refuses
`nothing_said` when no segment has text."""

import pytest
from ashley.runs.captions import Segment, lines_of, spoken
from ashley.workshop.reader import Recording, page_of
from ashley.inference.model import ToolCall
from transcript_playback_blind_support import MP3, MP4, go, scene


def test_the_transcript_names_its_recording_and_the_start_of_each_line(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            clip = await s.put(MP4, "talk.mp4")
            got = await s.transcribe(clip, (0, "welcome"), (75.4, "the middle"), (3700, "the end"))
            assert not got.is_error
            (made,) = [p for p in await s.pieces() if p.kind == "reader"]
            page = page_of(made.text.body)
            assert page is not None
            assert page.recording == Recording(clip.id, (0.0, 75.4, 3700.0))
            assert len(page.text.split("\n")) == 3

    go(scenario())


def test_an_audio_recording_is_named_too(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            audio = await s.put(MP3, "talk.mp3")
            await s.transcribe(audio, (2, "a"), (3, "b"))
            (made,) = [p for p in await s.pieces() if p.kind == "reader"]
            page = page_of(made.text.body)
            assert page is not None and page.recording == Recording(audio.id, (2.0, 3.0))

    go(scenario())


def test_a_segment_without_text_has_no_line_and_no_start(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            clip = await s.put(MP4, "talk.mp4")
            await s.transcribe(clip, (0, "one"), (5, ""), (6, "   "), (9, "two"), (12, ""))
            (made,) = [p for p in await s.pieces() if p.kind == "reader"]
            page = page_of(made.text.body)
            assert page is not None
            assert page.recording == Recording(clip.id, (0.0, 9.0))
            assert [ln.split("]")[0] for ln in page.text.split("\n")] == ["[0:00", "[0:09"]

    go(scenario())


def test_starts_follow_the_order_the_segments_were_given_in_and_match_the_lines(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            clip = await s.put(MP4, "talk.mp4")
            segs = [(30, "x"), (10, ""), (20, "y")]
            await s.transcribe(clip, *segs)
            (made,) = [p for p in await s.pieces() if p.kind == "reader"]
            page = page_of(made.text.body)
            assert page is not None and page.recording is not None
            made_segments = [Segment(t, w) for t, w in segs]
            assert page.text == lines_of(made_segments)
            assert page.recording.starts == tuple(seg.start for seg in spoken(made_segments))

    go(scenario())


@pytest.mark.parametrize("lines", [(), ((0, ""),), ((0, ""), (4, "  \t"))])
def test_no_segment_with_text_is_nothing_said_and_changes_nothing(db_url: str, lines: tuple[tuple[float, str], ...]) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            clip = await s.put(MP4, "talk.mp4")
            before = await s.pieces()
            got = await s.transcribe(clip, *lines)
            assert got.is_error and "nothing_said" in got.content
            assert await s.pieces() == before

    go(scenario())


def test_a_transcript_is_not_a_page_of_the_web(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            clip = await s.put(MP4, "talk.mp4")
            await s.transcribe(clip, (0, "hi"))
            (made,) = [p for p in await s.pieces() if p.kind == "reader"]
            page = page_of(made.text.body)
            assert page is not None and page.url == ""

    go(scenario())


SRT = "1\n00:00:01,000 --> 00:00:03,000\nhello there\n\n2\n00:01:05,500 --> 00:01:07,000\nsecond line\n"


def test_a_transcript_from_a_captions_file_names_the_recording_and_each_cue_start(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            clip = await s.put(MP4, "talk.mp4")
            captions = await s.put(SRT.encode(), "talk.srt")
            got = await s.tools().call(ToolCall("c2", "bench_transcribe", {"piece_id": clip.id, "captions_piece": captions.id}))
            assert not got.is_error
            (made,) = [p for p in await s.pieces() if p.kind == "reader"]
            page = page_of(made.text.body)
            assert page is not None
            assert page.recording == Recording(clip.id, (1.0, 65.5))
            assert page.text == "[0:01] hello there\n[1:05] second line"

    go(scenario())
