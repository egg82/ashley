"""`bench_transcribe` with a captions file piece (`captions_piece`, a `.srt` or `.vtt` file piece): its cues are the
transcript and the worker is not asked; and what the log says of where the words came from."""

import logging
import pytest
from ashley.workshop.model import Piece
from ashley.workshop.reader import page_of
from bench_media_blind_support import MP4, SRT, SRT_LINES, VTT, Scene, call, fields_of, go, log_text, said, scene, sha


async def with_clip(s: Scene) -> Piece:
    return await s.put(MP4, "talk.mp4")


async def readers(s: Scene) -> list[Piece]:
    return [p for p in await s.pieces() if p.kind == "reader"]


async def transcript_of(s: Scene) -> Piece:
    (made,) = await readers(s)
    return made


def lines(piece: Piece) -> list[str]:
    page = page_of(piece.text.body)
    assert page is not None
    return page.text.splitlines()


async def captions_file(s: Scene, name: str, text: str) -> Piece:
    return await s.put(text.encode(), name)


@pytest.mark.parametrize(("name", "text"), [("talk.srt", SRT), ("talk.vtt", VTT), ("TALK.SRT", SRT)])
def test_a_captions_file_she_names_is_used_and_the_worker_is_not_asked(db_url: str, name: str, text: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            clip = await with_clip(s)
            sidecar = await captions_file(s, name, text)
            got = await s.tools().call(call("bench_transcribe", piece_id=clip.id, captions_piece=sidecar.id))
            assert not got.is_error and s.media.jobs() == 0
            assert lines(await transcript_of(s)) == SRT_LINES.splitlines()

    go(scenario())


def test_a_captions_file_wins_over_whatever_the_worker_would_say_and_ignores_the_language(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            clip = await with_clip(s)
            s.media.words_to_give = said((0, "the sound says something else"), source="captions")
            sidecar = await captions_file(s, "talk.srt", SRT)
            await s.tools().call(call("bench_transcribe", piece_id=clip.id, captions_piece=sidecar.id, language="fr"))
            assert "something else" not in (await transcript_of(s)).text.body and s.media.jobs() == 0

    go(scenario())


def test_captions_in_a_file_piece_are_read_as_stamped_lines(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            clip = await with_clip(s)
            sidecar = await captions_file(s, "t.srt", SRT.replace("\n", "\r\n"))
            await s.tools().call(call("bench_transcribe", piece_id=clip.id, captions_piece=sidecar.id))
            page = page_of((await transcript_of(s)).text.body)
            assert page is not None and page.text.strip() == SRT_LINES

    go(scenario())


def test_without_a_captions_file_the_workers_captions_or_speech_are_the_transcript(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            clip = await with_clip(s)
            s.media.words_to_give = said((2, "from the file"), source="captions")
            await s.tools().call(call("bench_transcribe", piece_id=clip.id))
            assert lines(await transcript_of(s)) == ["[0:02] from the file"] and len(s.media.transcribe_jobs) == 1

    go(scenario())


@pytest.mark.parametrize("source", ["captions", "speech"])
def test_the_log_says_where_the_words_came_from(db_url: str, source: str, caplog: pytest.LogCaptureFixture) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            clip = await with_clip(s)
            s.media.words_to_give = said((2, "a private sentence"), source=source)
            with caplog.at_level(logging.DEBUG):
                await s.tools().call(call("bench_transcribe", piece_id=clip.id))
            (event,) = fields_of(caplog, "tools.call")
            assert event["tool"] == "bench_transcribe" and event["bench"] == s.bench and event["piece"] == clip.id
            assert event["source"] == source and event["outcome"] == "ok"

    go(scenario())


def test_a_captions_file_is_logged_as_captions_not_speech(db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            clip = await with_clip(s)
            sidecar = await captions_file(s, "t.srt", SRT)
            with caplog.at_level(logging.DEBUG):
                await s.tools().call(call("bench_transcribe", piece_id=clip.id, captions_piece=sidecar.id))
            (event,) = fields_of(caplog, "tools.call")
            assert event["source"] != "speech" and event["outcome"] == "ok"

    go(scenario())


def test_the_log_carries_no_word_of_the_recording(db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            clip = await with_clip(s)
            sidecar = await captions_file(s, "t.srt", "1\n00:00:01,000 --> 00:00:02,000\nxylophone zeppelin\n")
            s.media.words_to_give = said((2, "quizzical wombat"))
            with caplog.at_level(logging.DEBUG):
                await s.tools().call(call("bench_transcribe", piece_id=clip.id, captions_piece=sidecar.id))
                await s.tools().call(call("bench_transcribe", piece_id=clip.id, language="fr"))
            text = log_text(caplog)
            assert "xylophone" not in text and "zeppelin" not in text and "wombat" not in text
            assert "talk.mp4" not in text and sha(MP4) not in text and "/api/files/" not in text

    go(scenario())


