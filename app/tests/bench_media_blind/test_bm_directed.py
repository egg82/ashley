"""Directed tests for what a planted wrong implementation got past the contract tests (see MUTANTS.txt)."""

import logging
from typing import Any

import pytest
from ashley.runs.captions import Segment, lines_of, parse_captions
from ashley.workshop import reader
from ashley.workshop.commands import Add, Cue
from ashley.workshop.model import HER, Text
from bench_media_blind_support import MP3, MP4, PDF, SRT, call, fields_of, go, said, scene, sheet


def test_a_recording_with_a_long_file_name_is_still_transcribed(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            clip = await s.put(MP4, "n" * 190 + ".mp4")
            got = await s.tools().call(call("bench_transcribe", piece_id=clip.id))
            assert not got.is_error and len([p for p in await s.pieces() if p.kind == "reader"]) == 1

    go(scenario())


def test_each_transcription_job_has_a_name_of_its_own(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            clip = await s.put(MP4, "v.mp4")
            for _ in range(3):
                await s.tools().call(call("bench_transcribe", piece_id=clip.id))
            names = [n for n, _, _ in s.media.transcribe_jobs]
            assert len(set(names)) == 3 and all(n.startswith("media-") for n in names)

    go(scenario())


def test_the_frame_count_the_worker_reports_is_what_the_log_says(db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            clip = await s.put(MP4, "v.mp4")
            s.media.sheet_to_give = sheet(3)
            with caplog.at_level(logging.DEBUG):
                got = await s.tools().call(call("bench_frames", piece_id=clip.id, at=[1, 2, 3]))
            (event,) = fields_of(caplog, "tools.call")
            assert event["frames"] == 3 and event["bytes"] == len(got.images[0].data)

    go(scenario())


def test_the_specs_name_their_arguments_and_which_are_needed(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            specs = {x.name: x for x in (await s.tools().catalogue()).specs}
            frames: Any = specs["bench_frames"].parameters
            words: Any = specs["bench_transcribe"].parameters
            assert set(frames["properties"]) == {"piece_id", "at"} and set(frames["required"]) == {"piece_id", "at"}
            assert set(words["properties"]) == {"piece_id", "captions_piece", "language"} and words["required"] == ["piece_id"]
            assert frames["properties"]["at"]["type"] == "array" and frames["properties"]["piece_id"]["type"] == "integer"

    go(scenario())


def test_a_whitespace_only_text_is_not_a_line() -> None:
    assert lines_of([Segment(1, "one"), Segment(2, "   "), Segment(3, "\n")]).splitlines() == ["[0:01] one"]


def test_a_byte_order_mark_before_the_first_cue_is_not_part_of_it() -> None:
    assert parse_captions("﻿00:00:01,000 --> 00:00:02,000\nfirst\n") == [Segment(1.0, "first")]
    assert parse_captions("﻿WEBVTT\n\n00:01.000 --> 00:02.000\nfirst\n") == [Segment(1.0, "first")]


@pytest.mark.parametrize(("url", "ok"), [("", True), ("https://example.com/page", True), ("http://example.com/page", False),
                                         ("ftp://example.com/x", False), ("not a url", False)])
def test_a_reader_has_no_address_or_an_https_one(db_url: str, url: str, ok: bool) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            got = await s.workshop.apply(s.alana, s.bench, Add(HER, "reader", Text("t", reader.body_of(url, "", "[0:01] words")), "medium"))
            assert (got.outcome == "accepted") is ok

    go(scenario())


def test_a_transcript_reads_back_as_a_page_of_its_lines(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            clip = await s.put(MP3, "a.mp3")
            s.media.words_to_give = said((5, "alpha beta"), (65, "gamma"))
            await s.tools().call(call("bench_transcribe", piece_id=clip.id))
            made = [p for p in await s.pieces() if p.kind == "reader"][0]
            page = reader.page_of(made.text.body)
            assert page is not None and page.paragraphs == ("[0:05] alpha beta", "[1:05] gamma")

    go(scenario())


def test_the_log_counts_the_frames_the_worker_gave_not_the_moments_asked(db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            clip = await s.put(MP4, "v.mp4")
            s.media.sheet_to_give = sheet(2)
            with caplog.at_level(logging.DEBUG):
                await s.tools().call(call("bench_frames", piece_id=clip.id, at=[1, 2, 3]))
            (event,) = fields_of(caplog, "tools.call")
            assert event["frames"] == 2

    go(scenario())


def test_a_captions_piece_that_is_a_boolean_is_not_a_piece_number(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            sidecar = await s.put(SRT.encode(), "talk.srt")
            clip = await s.put(MP4, "v.mp4")
            assert sidecar.id == 1
            got = await s.tools().call(call("bench_transcribe", piece_id=clip.id, captions_piece=True))
            assert got.is_error and [p for p in await s.pieces() if p.kind == "reader"] == []

    go(scenario())


def test_the_captions_file_named_is_the_one_used_not_another_file_piece(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            await s.put(PDF, "first.pdf")
            clip = await s.put(MP4, "v.mp4")
            sidecar = await s.put(SRT.encode(), "talk.srt")
            got = await s.tools().call(call("bench_transcribe", piece_id=clip.id, captions_piece=sidecar.id))
            assert not got.is_error and s.media.jobs() == 0

    go(scenario())


def test_cues_separated_by_a_line_of_spaces_are_still_two_cues() -> None:
    from ashley.runs.captions import parse_captions

    text = "1\n00:00:01,000 --> 00:00:02,000\nfirst\n \t \n2\n00:00:03,000 --> 00:00:04,000\nsecond\n"
    assert [(c.start, c.text) for c in parse_captions(text)] == [(1.0, "first"), (3.0, "second")]


def test_a_reader_piece_has_no_player_to_cue(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            clip = await s.put(MP4, "v.mp4")
            s.media.words_to_give = said((1, "x"))
            await s.tools().call(call("bench_transcribe", piece_id=clip.id))
            made = [p for p in await s.pieces() if p.kind == "reader"][0]
            assert (await s.workshop.apply(s.alana, s.bench, Cue(HER, made.id, "play", None))).outcome != "accepted"

    go(scenario())
