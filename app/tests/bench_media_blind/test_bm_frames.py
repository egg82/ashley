"""`bench_frames`: a video (`clip`) piece at up to `max_frames` moments, brought back as one picture in the result, kept
with the turn like a look (object store under the looks' prefix, one `bench_looks` row per call) and counted with the
turn's looks against `max_looks_per_turn`. Bad calls and failed jobs are error results and change nothing."""

import logging
import math
import re
from typing import Any

import pytest
from ashley import services
from ashley.files.intake import key_of as file_key
from ashley.files.store import NullStore, ObjectStore
from ashley.looks.keys import PREFIX, key_of
from ashley.runs.media import Media, MediaUnavailable, NullMedia
from bench_media_blind_support import (JPEG, MEDIA, MP3, MP4, PDF, PNG, Scene, call, fields_of, go, log_text, scene, sha, sheet, take)

BAD_AT: list[tuple[str, Any]] = [
    ("empty", []), ("too many", [0, 1, 2, 3, 4, 5, 6]), ("negative", [-1]), ("negative among good", [1, 2, -0.5]),
    ("nan", [math.nan]), ("infinite", [math.inf]), ("negative infinite", [-math.inf]), ("a string", ["10"]),
    ("a null", [None]), ("not a list", 5), ("a bare string", "1,2"), ("an object", {"0": 1}),
]


async def clip_scene(s: Scene) -> int:
    return (await s.put(MP4, "v.mp4")).id


def untouched(s: Scene, before_log: int) -> Any:
    async def check() -> None:
        assert s.media.jobs() == 0
        assert s.store.puts() == [] or all(not k.startswith(PREFIX) for k in s.store.puts())
        assert s.looks_of() == []
        assert await s.log_size() == before_log

    return check()


def test_it_is_offered_only_with_a_store_and_a_media_worker(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            assert [x.name for x in (await s.tools().catalogue()).specs] == ["bench_frames", "bench_transcribe"]
            services.register(Media, NullMedia())
            assert (await s.tools().catalogue()).specs == ()
            services.register(Media, s.media)
            services.register(ObjectStore, NullStore())
            assert (await s.tools().catalogue()).specs == ()

    go(scenario())


def test_frames_is_a_read_and_transcribe_is_a_change(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            specs = {x.name: x for x in (await s.tools().catalogue()).specs}
            assert specs["bench_frames"].reads is True and specs["bench_transcribe"].reads is False

    go(scenario())


def test_the_picture_comes_back_in_the_result_as_the_sheet_the_worker_made(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            clip = await clip_scene(s)
            s.media.sheet_to_give = sheet(3, JPEG + b"-three")
            got = await s.tools().call(call("bench_frames", piece_id=clip, at=[1, 20.5, 3]))
            assert not got.is_error
            (image,) = got.images
            assert image.data == JPEG + b"-three" and image.media_type == "image/jpeg"

    go(scenario())


def test_the_worker_is_asked_for_the_file_and_the_moments_in_the_order_given(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            clip = await clip_scene(s)
            await s.tools().call(call("bench_frames", piece_id=clip, at=[30, 0, 7.25]))
            ((name, source, at),) = s.media.frame_jobs
            assert at == (30.0, 0.0, 7.25)
            assert (source.household_id, source.sha256, source.size, source.media_type) == (s.alana.household_id, sha(MP4), len(MP4), "video/mp4")
            assert re.fullmatch(r"media-[a-z0-9-]+", name) and len(name) <= 63

    go(scenario())


def test_each_job_has_a_name_of_its_own(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            clip = await clip_scene(s)
            for _ in range(3):
                await s.tools().call(call("bench_frames", piece_id=clip, at=[1]))
            assert len({n for n, _, _ in s.media.frame_jobs}) == 3

    go(scenario())


@pytest.mark.parametrize("count", [1, MEDIA.max_frames])
def test_one_up_to_the_most_frames_is_taken(db_url: str, count: int) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            clip = await clip_scene(s)
            got = await s.tools().call(call("bench_frames", piece_id=clip, at=list(range(count))))
            assert not got.is_error and s.media.frame_jobs[0][2] == tuple(float(i) for i in range(count))

    go(scenario())


def test_a_moment_of_zero_and_whole_seconds_are_taken(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            clip = await clip_scene(s)
            assert not (await s.tools().call(call("bench_frames", piece_id=clip, at=[0, 0.0, 5, 7200]))).is_error

    go(scenario())


def test_the_picture_is_kept_under_the_looks_prefix_not_the_files(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            clip = await clip_scene(s)
            s.media.sheet_to_give = sheet(2, JPEG + b"-kept")
            await s.tools().call(call("bench_frames", piece_id=clip, at=[1, 2]))
            key = key_of(s.alana.household_id, sha(JPEG + b"-kept"))
            assert s.store.held[key] == JPEG + b"-kept" and key.startswith("look/")
            assert file_key(s.alana.household_id, sha(JPEG + b"-kept")) not in s.store.held

    go(scenario())


def test_one_row_per_call_names_the_picture_the_bench_and_the_piece(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            clip = await clip_scene(s)
            s.media.sheet_to_give = sheet(2, JPEG + b"-row")
            c = call("bench_frames", piece_id=clip, at=[1, 2])
            await s.tools().call(c)
            (row,) = s.looks_of()
            assert row == (c.id, s.bench, clip, sha(JPEG + b"-row"), "image/jpeg", len(JPEG + b"-row"))
            (look,) = await s.looks.in_conversation(s.alana.household_id, s.conversation)
            assert (look.turn_id, look.conversation_id) == (s.turn, s.conversation)

    go(scenario())


def test_the_same_call_run_again_replaces_its_row(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            clip = await clip_scene(s)
            c = call("bench_frames", piece_id=clip, at=[1])
            await s.tools().call(c)
            s.media.sheet_to_give = sheet(1, JPEG + b"-again")
            await s.tools().call(c)
            assert [r[3] for r in s.looks_of()] == [sha(JPEG + b"-again")]

    go(scenario())


@pytest.mark.parametrize(("label", "at"), BAD_AT, ids=[b[0] for b in BAD_AT])
def test_a_bad_at_is_an_error_and_changes_nothing(db_url: str, label: str, at: Any) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            clip = await clip_scene(s)
            before = await s.log_size()
            got = await s.tools().call(call("bench_frames", piece_id=clip, at=at))
            assert got.is_error and got.images == ()
            await untouched(s, before)

    go(scenario())


def test_a_missing_at_or_piece_is_an_error(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            clip = await clip_scene(s)
            assert (await s.tools().call(call("bench_frames", piece_id=clip))).is_error
            assert (await s.tools().call(call("bench_frames", at=[1]))).is_error
            assert (await s.tools().call(call("bench_frames", piece_id="x", at=[1]))).is_error
            assert s.media.jobs() == 0 and s.looks_of() == []

    go(scenario())


async def pieces_of_every_other_sort(s: Scene) -> dict[str, int]:
    from ashley.workshop.commands import Add
    from ashley.workshop.model import HER, Text

    out = {"audio": (await s.put(MP3, "a.mp3")).id, "image": (await s.put(PNG, "p.png")).id, "file": (await s.put(PDF, "d.pdf")).id}
    note = await s.workshop.apply(s.alana, s.bench, Add(HER, "note", Text("n", "hi"), "small"))
    assert note.piece_id is not None
    out["note"] = note.piece_id
    return out


def test_only_a_clip_can_be_framed(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            others = await pieces_of_every_other_sort(s)
            before = await s.log_size()
            for kind, piece in others.items():
                got = await s.tools().call(call("bench_frames", piece_id=piece, at=[1]))
                assert got.is_error and got.images == (), kind
            await untouched(s, before)

    go(scenario())


def test_a_piece_that_is_not_on_the_bench_is_an_error(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            clip = await clip_scene(s)
            other = (await s.workshop.open(s.alana, "other")).id
            before = await s.log_size()
            for piece in (clip + 100, 0, -1):
                assert (await s.tools().call(call("bench_frames", piece_id=piece, at=[1]))).is_error
            assert (await s.tools(bench=other).call(call("bench_frames", piece_id=clip, at=[1]))).is_error
            await untouched(s, before)

    go(scenario())


def test_a_clip_on_the_shelf_is_not_framed(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            from ashley.workshop.commands import Archive
            from ashley.workshop.model import HER

            clip = await clip_scene(s)
            await s.workshop.apply(s.alana, s.bench, Archive(HER, clip))
            assert (await s.tools().call(call("bench_frames", piece_id=clip, at=[1]))).is_error
            assert s.media.jobs() == 0

    go(scenario())


@pytest.mark.parametrize("reason", ["no_video", "unreadable", "no_frame", "wrong_file", "too_large", "timed_out"])
def test_a_job_that_cannot_be_done_is_an_error_result_that_keeps_nothing(db_url: str, reason: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            clip = await clip_scene(s)
            s.media.sheet_to_give = MediaUnavailable(reason)
            before = await s.log_size()
            got = await s.tools().call(call("bench_frames", piece_id=clip, at=[1]))
            assert got.is_error and got.images == ()
            assert s.looks_of() == [] and not [k for k in s.store.held if k.startswith(PREFIX)]
            assert await s.log_size() == before

    go(scenario())


def test_the_reason_she_is_told_for_a_recording_with_no_picture_names_it(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            from ashley.tools.bench_media import CANNOT

            clip = await clip_scene(s)
            s.media.sheet_to_give = MediaUnavailable("no_video")
            got = await s.tools().call(call("bench_frames", piece_id=clip, at=[1]))
            assert CANNOT["no_video"] in got.content

    go(scenario())


def test_when_the_store_is_down_nothing_is_recorded_and_she_is_told(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            clip = await clip_scene(s)
            s.store.fail = frozenset({"put"})
            got = await s.tools().call(call("bench_frames", piece_id=clip, at=[1]))
            assert got.is_error and s.looks_of() == []

    go(scenario())


def test_it_changes_nothing_on_the_bench(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            clip = await clip_scene(s)
            before_pieces, before_log = await s.pieces(), await s.log_size()
            await take(s, clip)
            assert await s.pieces() == before_pieces and await s.log_size() == before_log

    go(scenario())


def test_it_logs_ids_and_counts_and_never_a_word_or_a_link(db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            from ashley.workshop.commands import Edit
            from ashley.workshop.model import HER, Text

            clip = await clip_scene(s)
            await s.workshop.apply(s.alana, s.bench, Edit(HER, clip, 1, Text("A secret holiday title", (await s.pieces())[0].text.body)))
            with caplog.at_level(logging.DEBUG):
                await take(s, clip)
                await s.tools().call(call("bench_frames", piece_id=clip, at=[-1]))
            events = fields_of(caplog, "tools.call")
            assert len(events) == 2
            assert all(e["tool"] == "bench_frames" and e["bench"] == s.bench for e in events)
            assert events[0]["piece"] == clip and events[0]["frames"] == 1 and events[0]["outcome"] == "ok"
            assert events[1]["outcome"] != "ok"
            text = log_text(caplog)
            assert "secret holiday" not in text and "/api/files/" not in text and JPEG.hex() not in text
            assert sha(MP4) not in text and "v.mp4" not in text

    go(scenario())
