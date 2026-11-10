"""`bench_transcribe`: the words of a `clip` or `audio` piece as a reader piece with no address, one stamped line per
segment, placed beside the recording. Captions come first from a `.srt`/`.vtt` file piece she names (`captions_piece`,
parsed in the app), else from the captions inside the file or the sound (the media worker). Errors change nothing."""

import logging
from typing import Any

import pytest
from ashley.runs.media import MediaUnavailable
from ashley.tools.bench_media import CANNOT
from ashley.workshop.commands import Add, Archive
from ashley.workshop.model import HER, Piece, Text
from ashley.workshop.reader import page_of
from bench_media_blind_support import (FILES, LOOKS, MP3, MP4, PDF, PNG, RULES, SRT, Scene, body, call, fields_of, go,
                                       said, scene, sha, sheet)


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


def test_the_speech_becomes_a_reader_piece_of_stamped_lines_with_no_address(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            clip = await with_clip(s)
            s.media.words_to_give = said((0, "welcome"), (75.4, "the middle part"), (3700, "the end"))
            got = await s.tools().call(call("bench_transcribe", piece_id=clip.id))
            assert not got.is_error
            made = await transcript_of(s)
            page = page_of(made.text.body)
            assert page is not None and page.url == ""
            assert lines(made) == ["[0:00] welcome", "[1:15] the middle part", "[1:01:40] the end"]
            assert str(made.id) in got.content

    go(scenario())


def test_the_worker_is_asked_for_the_recording_and_the_language(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            clip = await with_clip(s)
            await s.tools().call(call("bench_transcribe", piece_id=clip.id, language="en"))
            ((name, source, language),) = s.media.transcribe_jobs
            assert language == "en" and name.startswith("media-")
            assert (source.household_id, source.sha256, source.size, source.media_type) == (s.alana.household_id, sha(MP4), len(MP4), "video/mp4")

    go(scenario())


def test_no_language_asks_for_none(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            clip = await with_clip(s)
            await s.tools().call(call("bench_transcribe", piece_id=clip.id))
            assert s.media.transcribe_jobs[0][2] is None

    go(scenario())


def test_an_audio_piece_is_transcribed_too(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            audio = await s.put(MP3, "talk.mp3")
            got = await s.tools().call(call("bench_transcribe", piece_id=audio.id))
            assert not got.is_error
            assert s.media.transcribe_jobs[0][1].media_type == "audio/mpeg"
            assert len(await readers(s)) == 1

    go(scenario())


@pytest.mark.parametrize("language", ["en", "eng", "pt-BR", "zh-Hans", "en-US", "sr-Latn2", "en-ab", "en-abcdefgh"])
def test_a_language_code_is_passed_on(db_url: str, language: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            clip = await with_clip(s)
            got = await s.tools().call(call("bench_transcribe", piece_id=clip.id, language=language))
            assert not got.is_error and s.media.transcribe_jobs[0][2] == language

    go(scenario())


@pytest.mark.parametrize("language", ["e", "engl", "en-a", "en-abcdefghi", "english", "en_US", "en-", "-en", "en US", "e1", "en-U", "12", "en-toolongsubtag", "en;rm", "../x", 5, ["en"], True])
def test_a_language_that_is_not_a_short_code_is_an_error_and_changes_nothing(db_url: str, language: Any) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            clip = await with_clip(s)
            before = await s.log_size()
            got = await s.tools().call(call("bench_transcribe", piece_id=clip.id, language=language))
            assert got.is_error
            assert s.media.jobs() == 0 and await s.log_size() == before and await readers(s) == []

    go(scenario())


def test_the_reader_is_put_beside_the_recording(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            from ashley.workshop.commands import Add

            first = await s.workshop.apply(s.alana, s.bench, Add(HER, "note", Text("first", "x"), "small"))
            clip = await with_clip(s)
            await s.workshop.apply(s.alana, s.bench, Add(HER, "note", Text("last", "x"), "small"))
            await s.tools().call(call("bench_transcribe", piece_id=clip.id))
            made = await transcript_of(s)
            (clip_now,) = [p for p in await s.pieces() if p.id == clip.id]
            assert abs(made.place.order - clip_now.place.order) == 1
            assert first.piece_id is not None

    go(scenario())


def test_it_is_her_add_of_one_reader_and_leaves_the_recording_alone(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            clip = await with_clip(s)
            before = await s.log_size()
            await s.tools().call(call("bench_transcribe", piece_id=clip.id))
            new = (await s.workshop.log(s.alana, s.bench))[before:]
            assert new and all(row.outcome == "accepted" and row.by.author == "ashley" for row in new)
            adds = [row.command for row in new if type(row.command) is Add]
            assert [a.kind for a in adds] == ["reader"]
            assert all(getattr(row.command, "piece_id", None) != clip.id for row in new)
            (now,) = [p for p in await s.pieces() if p.id == clip.id]
            assert now.text == clip.text and now.version == clip.version

    go(scenario())


def test_it_makes_no_look_and_does_not_count_against_the_limit(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            clip = await with_clip(s)
            for i in range(LOOKS.max_looks_per_turn):
                s.media.sheet_to_give = sheet(1, b"\xff\xd8\xff" + bytes([i]))
                await s.tools().call(call("bench_frames", piece_id=clip.id, at=[1]))
            got = await s.tools().call(call("bench_transcribe", piece_id=clip.id))
            assert not got.is_error and len(s.looks_of()) == LOOKS.max_looks_per_turn

    go(scenario())


def test_a_words_job_keeps_no_picture(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            clip = await with_clip(s)
            await s.tools().call(call("bench_transcribe", piece_id=clip.id))
            assert s.looks_of() == [] and not [k for k in s.store.puts() if k.startswith("look/")]

    go(scenario())


def test_segments_with_no_text_are_left_out_of_the_transcript(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            clip = await with_clip(s)
            s.media.words_to_give = said((1, "one"), (2, ""), (3, "three"))
            await s.tools().call(call("bench_transcribe", piece_id=clip.id))
            assert lines(await transcript_of(s)) == ["[0:01] one", "[0:03] three"]

    go(scenario())


async def other_pieces(s: Scene) -> dict[str, int]:
    note = await s.workshop.apply(s.alana, s.bench, Add(HER, "note", Text("n", "hi"), "small"))
    assert note.piece_id is not None
    return {"image": (await s.put(PNG, "p.png")).id, "file": (await s.put(PDF, "d.pdf")).id, "note": note.piece_id}


def test_only_a_clip_or_an_audio_piece_is_transcribed(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            others = await other_pieces(s)
            before = await s.log_size()
            for kind, piece in others.items():
                assert (await s.tools().call(call("bench_transcribe", piece_id=piece))).is_error, kind
            assert (await s.tools().call(call("bench_transcribe", piece_id=999))).is_error
            assert s.media.jobs() == 0 and await s.log_size() == before

    go(scenario())


def test_a_reader_piece_cannot_be_transcribed_as_if_it_were_a_recording(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            clip = await with_clip(s)
            await s.tools().call(call("bench_transcribe", piece_id=clip.id))
            made = await transcript_of(s)
            again = await s.tools().call(call("bench_transcribe", piece_id=made.id))
            assert again.is_error and len(await readers(s)) == 1

    go(scenario())


def test_a_missing_or_badly_typed_piece_id_is_an_error(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            assert (await s.tools().call(call("bench_transcribe"))).is_error
            assert (await s.tools().call(call("bench_transcribe", piece_id="one"))).is_error
            assert s.media.jobs() == 0

    go(scenario())


def test_a_clip_on_another_bench_or_the_shelf_is_not_transcribed(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            clip = await with_clip(s)
            elsewhere = (await s.workshop.open(s.alana, "other")).id
            assert (await s.tools(bench=elsewhere).call(call("bench_transcribe", piece_id=clip.id))).is_error
            await s.workshop.apply(s.alana, s.bench, Archive(HER, clip.id))
            assert (await s.tools().call(call("bench_transcribe", piece_id=clip.id))).is_error
            assert s.media.jobs() == 0 and await readers(s) == []

    go(scenario())


def test_a_captions_piece_that_is_not_captions_is_an_error_and_changes_nothing(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            clip = await with_clip(s)
            others = await other_pieces(s)
            before = await s.log_size()
            for kind, piece in {**others, "missing": 999, "itself": clip.id}.items():
                got = await s.tools().call(call("bench_transcribe", piece_id=clip.id, captions_piece=piece))
                assert got.is_error, kind
            assert await s.log_size() == before and await readers(s) == []

    go(scenario())


def test_a_captions_piece_must_be_an_integer(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            clip = await with_clip(s)
            sidecar = await captions_file(s, "talk.srt", SRT)
            for bad in ("1", [sidecar.id], 1.5):
                assert (await s.tools().call(call("bench_transcribe", piece_id=clip.id, captions_piece=bad))).is_error
            assert await readers(s) == [] and s.media.jobs() == 0

    go(scenario())


def test_a_captions_file_with_no_cue_makes_no_empty_transcript(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            clip = await with_clip(s)
            blank = await captions_file(s, "empty.srt", "this is not a captions file at all\n")
            got = await s.tools().call(call("bench_transcribe", piece_id=clip.id, captions_piece=blank.id))
            made = await readers(s)
            assert got.is_error or s.media.transcribe_jobs
            assert all(lines(p) for p in made)

    go(scenario())


@pytest.mark.parametrize("reason", ["no_audio", "too_long", "no_speech_service", "speech_down", "unreadable", "wrong_file", "timed_out"])
def test_a_job_that_cannot_be_done_is_an_error_that_adds_nothing(db_url: str, reason: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            clip = await with_clip(s)
            s.media.words_to_give = MediaUnavailable(reason)
            before = await s.log_size()
            got = await s.tools().call(call("bench_transcribe", piece_id=clip.id))
            assert got.is_error
            if reason in CANNOT:
                assert CANNOT[reason] in got.content
            assert await s.log_size() == before and await readers(s) == []

    go(scenario())


def test_the_failure_is_logged_not_as_a_success(db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            clip = await with_clip(s)
            s.media.words_to_give = MediaUnavailable("speech_down")
            with caplog.at_level(logging.DEBUG):
                await s.tools().call(call("bench_transcribe", piece_id=clip.id))
            (event,) = fields_of(caplog, "tools.call")
            assert event["outcome"] != "ok" and event["bench"] == s.bench

    go(scenario())


def test_a_full_bench_takes_no_transcript_and_the_call_says_so(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            clip = await with_clip(s)
            while len(await s.pieces()) < RULES.max_pieces:
                await s.workshop.apply(s.alana, s.bench, Add(HER, "note", Text("n", "x"), "small"))
            before_pieces, before = await s.pieces(), await s.log_size()
            got = await s.tools().call(call("bench_transcribe", piece_id=clip.id))
            assert got.is_error
            assert len(await s.pieces()) == len(before_pieces)
            assert await readers(s) == []
            assert await s.log_size() <= before + 1

    go(scenario())


def test_the_result_is_text_she_can_read_without_the_words_being_repeated_as_a_picture(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            clip = await with_clip(s)
            got = await s.tools().call(call("bench_transcribe", piece_id=clip.id))
            assert got.images == () and isinstance(body(got), (dict, list, str))

    go(scenario())


def test_the_media_kinds_play_in_the_shipped_files_config() -> None:
    assert FILES.plays("audio/mpeg") and FILES.plays("video/webm")


async def captions_file(s: Scene, name: str, text: str) -> Piece:
    return await s.put(text.encode(), name)
