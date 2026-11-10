"""`bench_transcribe` on a video piece of a YouTube video: it puts the words beside the video as a reader piece that names
it, from the captions file piece she names (the media worker is not asked) or else the video's English captions, which the
worker fetches given the video's id alone; a video with no English track has its own outcome and adds nothing; a video that
is not YouTube's is not a recording."""

import json

from ashley import services
from ashley.workshop import reader
from ashley.workshop.commands import Add
from ashley.workshop.model import HER, Text
from ashley.workshop.workshop import Workshop
from files_support import sync
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from test_bench_media import Worker, World, seen, world
from youtube_read_support import VIDEO, WATCH


async def video(w: World, url: str = WATCH) -> int:
    added = await services.get(Workshop).apply(w.owner, w.bench, Add(HER, "video", Text("Dough", json.dumps({"url": url})), "medium"))
    assert added.piece_id is not None
    return added.piece_id


@sync
async def test_a_youtube_video_is_transcribed_from_the_captions_file_she_names_beside_the_video(db_url: str) -> None:
    async with world(db_url) as w:
        piece = await video(w)
        got = await w.transcribe(piece_id=piece, captions_piece=w.subs)
        assert not got.is_error, got.content
        assert (seen(got)["source"], seen(got)["segments"]) == ("captions", 2) and w.worker.transcripts_asked == []
        view = await services.get(Workshop).read(w.owner, w.bench)
        order = [p.id for p in view.pieces]
        made = next(p for p in view.pieces if p.id == seen(got)["piece_id"])
        assert order.index(made.id) == order.index(piece) + 1 and made.kind == "reader"
        page = reader.page_of(made.text.body)
        assert page is not None and page.title == "Transcript of Dough" and page.text == "[0:02] from the file\n[1:05] later on"
        assert page.recording == reader.Recording(piece, (2.0, 65.0))


@sync
async def test_a_youtube_video_without_a_captions_file_has_its_english_captions_fetched_by_id_alone(db_url: str) -> None:
    async with world(db_url) as w:
        piece = await video(w)
        got = await w.transcribe(piece_id=piece)
        assert not got.is_error, got.content
        assert (seen(got)["source"], seen(got)["segments"], seen(got)["seconds"]) == ("youtube", 2, 573)
        assert w.worker.youtube_asked == [VIDEO] and w.worker.transcripts_asked == []
        view = await services.get(Workshop).read(w.owner, w.bench)
        made = next(p for p in view.pieces if p.id == seen(got)["piece_id"])
        page = reader.page_of(made.text.body)
        assert page is not None and page.text == "[0:01] [music]\n[0:01] on October 10th"
        assert page.recording == reader.Recording(piece, (1.3, 1.8))


@sync
async def test_a_youtube_video_with_no_english_track_is_refused_in_its_own_outcome_and_adds_nothing(db_url: str) -> None:
    async with world(db_url, Worker(fails="no_captions")) as w:
        piece = await video(w)
        before = await w.pieces()
        got = await w.transcribe(piece_id=piece)
        assert got.is_error and got.content.startswith("no_english_captions:") and "captions_piece" in got.content
        assert await w.pieces() == before


@sync
async def test_a_failed_fetch_of_a_youtube_videos_captions_is_unavailable_and_adds_nothing(db_url: str) -> None:
    async with world(db_url, Worker(fails="timed_out")) as w:
        piece = await video(w)
        before = await w.pieces()
        got = await w.transcribe(piece_id=piece)
        assert got.is_error and got.content.startswith("unavailable:") and "timed_out" in got.content
        assert await w.pieces() == before


@sync
async def test_a_video_piece_that_is_not_a_youtube_video_is_not_a_recording(db_url: str) -> None:
    async with world(db_url) as w:
        for url in ("https://vimeo.com/76979871", "https://example.com/clip.mp4"):
            got = await w.transcribe(piece_id=await video(w, url), captions_piece=w.subs)
            assert got.is_error and got.content.startswith("not_a_recording:"), url
