"""`bench_frames` and `bench_transcribe` over the real Workshop, Postgres Looks and an in-memory store, with a fake media
worker: frames of a video piece are one picture in the result, kept with the turn and counted with the looks; a
transcript is a reader piece with stamped lines put beside the recording, from a captions file she names or from what the
worker heard; a piece that is not a recording, a bad argument and a worker that cannot do it are errors that change
nothing; the log names ids and counts, never what was said."""

import dataclasses
import hashlib
import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import pytest
from files_support import MP3, MP4, PNG, sync
from ashley import services
from ashley.db.pool import PoolDatabase
from ashley.files.memory import MemoryStore
from ashley.files.store import NullStore, ObjectStore
from ashley.inference.model import Image, ToolCall, ToolResult
from ashley.live.live import Live
from ashley.looks.keys import key_of as look_key
from ashley.looks.looks import Looks
from ashley.looks.postgres import PostgresLooks
from ashley.runs.captions import Segment
from ashley.runs.media import Media, MediaUnavailable, Sheet, Source, Transcribed
from ashley.tools import bench_media
from ashley.tools.bench_media import BenchMediaTools
from ashley.workshop import reader
from ashley.workshop import rules as workshop_rules
from ashley.workshop.bench_file import add_file
from ashley.workshop.commands import Add
from ashley.workshop.model import HER, Owner, Text
from ashley.workshop.postgres import PostgresWorkshop
from ashley.workshop.workshop import Workshop
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import household, person, scalar
from live_support import FakeLive

RULES = workshop_rules.load()
SHEET = b"\xff\xd8\xff\xe0" + b"m" * 40
SRT = b"1\n00:00:02,000 --> 00:00:03,000\nfrom the file\n\n2\n00:01:05,000 --> 00:01:06,000\nlater <i>on</i>\n"


@dataclass
class Worker(Media):
    can: bool = True
    fails: str | None = None
    heard: Transcribed = Transcribed("speech", 95.0, (Segment(0, "hello"), Segment(65.5, "so it goes")))
    youtube: Transcribed = Transcribed("youtube", 573.3, (Segment(1.3, "[music]"), Segment(1.8, "on October 10th")))
    youtube_asked: list[str] = field(default_factory=lambda: list[str]())
    frames_asked: list[tuple[Source, tuple[float, ...]]] = field(default_factory=lambda: list[tuple[Source, tuple[float, ...]]]())
    transcripts_asked: list[tuple[Source, str | None]] = field(default_factory=lambda: list[tuple[Source, str | None]]())

    def available(self) -> bool:
        return self.can

    async def frames(self, name: str, source: Source, at: tuple[float, ...]) -> Sheet:
        self.frames_asked.append((source, at))
        if self.fails:
            raise MediaUnavailable(self.fails)
        return Sheet(SHEET, len(at), 61.25)

    async def transcribe(self, name: str, source: Source, language: str | None) -> Transcribed:
        self.transcripts_asked.append((source, language))
        if self.fails:
            raise MediaUnavailable(self.fails)
        return self.heard

    async def youtube_captions(self, name: str, video_id: str) -> Transcribed:
        self.youtube_asked.append(video_id)
        if self.fails:
            raise MediaUnavailable(self.fails)
        return self.youtube


@dataclass
class World:
    url: str
    home: int
    owner: Owner
    bench: int
    conversation: int
    turn: int
    store: MemoryStore
    worker: Worker
    clip: int
    audio: int
    subs: int
    note: int

    def tools(self) -> BenchMediaTools:
        return BenchMediaTools(self.home, self.owner.person_id, self.bench, self.conversation, self.turn)

    async def frames(self, call_id: str = "f1", **args: object) -> ToolResult:
        return await self.tools().call(ToolCall(call_id, "bench_frames", args))

    async def transcribe(self, **args: object) -> ToolResult:
        return await self.tools().call(ToolCall("t1", "bench_transcribe", args))

    async def pieces(self) -> list[tuple[int, str, str]]:
        view = await services.get(Workshop).read(self.owner, self.bench)
        return [(p.id, p.kind, p.text.title) for p in view.pieces]

    def rows(self) -> list[tuple[str, int | None, int]]:
        found: list[list[Any]] | None = scalar(
            self.url, "SELECT json_agg(json_build_array(call_id, piece_id, size) ORDER BY id) FROM bench_looks")
        return [(r[0], r[1], r[2]) for r in (found or [])]


@asynccontextmanager
async def world(url: str, worker: Worker | None = None) -> AsyncGenerator[World]:
    home = household(url)
    owner = Owner(home, person(url, home))
    conversation = int(scalar(url, "INSERT INTO conversations (household_id, kind) VALUES (%s, 'chat') RETURNING id",
                              (home,)))
    turn = int(scalar(url, "INSERT INTO turns (conversation_id, household_id, author, text) "
                           "VALUES (%s, %s, 'person', 'watch') RETURNING id", (conversation, home)))
    database = PoolDatabase(url)
    await database.open()
    made = MemoryStore()
    chosen = worker or Worker()
    services.register(Live, FakeLive())
    services.register(Workshop, PostgresWorkshop(database, RULES))
    services.register(ObjectStore, made)
    services.register(Looks, PostgresLooks(database))
    services.register(Media, chosen)
    try:
        shop = services.get(Workshop)
        bench = await shop.open(owner, "shed")
        ids: list[int] = []
        for data, name in ((MP4, "talk.mp4"), (MP3, "song.mp3"), (SRT, "talk.srt")):
            _, added = await add_file(owner, bench.id, HER, data, name, "", RULES)
            assert added.piece_id is not None
            ids.append(added.piece_id)
        note = await shop.apply(owner, bench.id, Add(HER, "note", Text("memo", "hello"), "medium"))
        assert note.piece_id is not None
        yield World(url, home, owner, bench.id, conversation, turn, made, chosen, ids[0], ids[1], ids[2], note.piece_id)
    finally:
        for interface in (Live, Workshop, ObjectStore, Looks, Media):
            services.unregister(interface)
        await database.close()


def seen(result: ToolResult) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(result.content)
    return loaded


@sync
async def test_frames_are_one_picture_in_the_result_kept_with_the_turn_of_the_file_the_piece_names(db_url: str) -> None:
    async with world(db_url) as w:
        got = await w.frames(piece_id=w.clip, at=[1, 12.5, 40])
        assert not got.is_error, got.content
        assert got.images == (Image("image/jpeg", SHEET),)
        assert (seen(got)["frames"], seen(got)["at"], seen(got)["duration_s"]) == (3, [1.0, 12.5, 40.0], 61.2)
        (source, at), = w.worker.frames_asked
        assert source == Source(w.home, hashlib.sha256(MP4).hexdigest(), len(MP4), "video/mp4") and at == (1.0, 12.5, 40.0)
        assert w.rows() == [("f1", w.clip, len(SHEET))]
        assert w.store.objects[look_key(w.home, hashlib.sha256(SHEET).hexdigest())] == SHEET


@sync
async def test_the_same_call_run_again_replaces_its_picture_rather_than_adding_one(db_url: str) -> None:
    async with world(db_url) as w:
        await w.frames(piece_id=w.clip, at=[1])
        await w.frames(piece_id=w.clip, at=[2])
        assert len(w.rows()) == 1


@sync
async def test_frames_of_anything_but_a_video_piece_are_refused_and_the_worker_is_not_asked(db_url: str) -> None:
    async with world(db_url) as w:
        for piece in (w.audio, w.subs, w.note, 9999):
            got = await w.frames(piece_id=piece, at=[1])
            assert got.is_error and got.content.split(":")[0] in ("not_a_recording", "no_such_piece"), piece
        assert w.worker.frames_asked == [] and w.rows() == []


@pytest.mark.parametrize("at", [[], "1", [1, 2, 3, 4, 5, 6, 7], [-1], [float("inf")], [float("nan")], ["1"], [True], None],
                         ids=["empty", "string", "seven", "negative", "inf", "nan", "text", "bool", "none"])
@sync
async def test_bad_moments_are_a_bad_argument_that_asks_nothing(db_url: str, at: object) -> None:
    async with world(db_url) as w:
        got = await w.frames(piece_id=w.clip, at=at)
        assert got.is_error and got.content.startswith("bad_arguments:") and w.worker.frames_asked == []


@sync
async def test_unknown_and_missing_arguments_are_refused(db_url: str) -> None:
    async with world(db_url) as w:
        assert (await w.frames(piece_id=w.clip, at=[1], url="x")).content.startswith("bad_arguments:")
        assert (await w.frames(at=[1])).content.startswith("bad_arguments:")
        assert (await w.tools().call(ToolCall("x", "bench_listen", {}))).content.startswith("unknown_tool:")


@sync
async def test_frames_count_against_the_turns_pictures_with_the_looks(db_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bench_media, "LOOKS", dataclasses.replace(bench_media.LOOKS, max_looks_per_turn=2))
    async with world(db_url) as w:
        assert not (await w.frames("a", piece_id=w.clip, at=[1])).is_error
        assert not (await w.frames("b", piece_id=w.clip, at=[1])).is_error
        over = await w.frames("c", piece_id=w.clip, at=[1])
        assert over.is_error and over.content.startswith("limit:") and len(w.worker.frames_asked) == 2


@pytest.mark.parametrize("reason,said", [("no_video", "no picture"), ("too_large", "too large"), ("timed_out", "timed_out"),
                                         ("never_ran", "never_ran")])
@sync
async def test_a_worker_that_cannot_keeps_nothing_and_says_why(db_url: str, reason: str, said: str) -> None:
    async with world(db_url, Worker(fails=reason)) as w:
        got = await w.frames(piece_id=w.clip, at=[1])
        assert got.is_error and got.content.startswith("unavailable:") and said in got.content
        assert w.rows() == [] and not [k for k in w.store.objects if k.startswith("look/")]


@sync
async def test_a_transcript_is_a_reader_piece_of_stamped_lines_with_no_address_beside_the_recording(db_url: str) -> None:
    async with world(db_url) as w:
        got = await w.transcribe(piece_id=w.clip, language="en")
        assert not got.is_error, got.content
        assert (seen(got)["source"], seen(got)["segments"], seen(got)["seconds"]) == ("speech", 2, 95)
        assert w.worker.transcripts_asked[0][1] == "en"
        view = await services.get(Workshop).read(w.owner, w.bench)
        order = [p.id for p in view.pieces]
        made = next(p for p in view.pieces if p.id == seen(got)["piece_id"])
        assert order.index(made.id) == order.index(w.clip) + 1 and made.kind == "reader"
        page = reader.page_of(made.text.body)
        assert page is not None and page.url == "" and page.title == "Transcript of talk.mp4"
        assert page.text == "[0:00] hello\n[1:05] so it goes"
        assert page.recording == reader.Recording(w.clip, (0.0, 65.5))


@sync
async def test_an_audio_piece_is_transcribed_too(db_url: str) -> None:
    async with world(db_url) as w:
        assert not (await w.transcribe(piece_id=w.audio)).is_error
        assert w.worker.transcripts_asked[0][0].media_type == "audio/mpeg"


@sync
async def test_the_captions_file_she_names_is_used_and_the_worker_is_not_asked(db_url: str) -> None:
    async with world(db_url) as w:
        got = await w.transcribe(piece_id=w.clip, captions_piece=w.subs)
        assert not got.is_error and seen(got)["source"] == "captions" and w.worker.transcripts_asked == []
        view = await services.get(Workshop).read(w.owner, w.bench)
        made = next(p for p in view.pieces if p.id == seen(got)["piece_id"])
        page = reader.page_of(made.text.body)
        assert page is not None and page.text == "[0:02] from the file\n[1:05] later on"


@sync
async def test_a_captions_piece_that_is_not_captions_is_refused_and_nothing_is_added(db_url: str) -> None:
    async with world(db_url) as w:
        before = await w.pieces()
        for piece in (w.note, w.clip, 9999, "x"):
            got = await w.transcribe(piece_id=w.clip, captions_piece=piece)
            assert got.is_error and got.content.split(":")[0] in ("no_captions", "bad_arguments"), piece
        assert await w.pieces() == before and w.worker.transcripts_asked == []


@sync
async def test_nothing_heard_is_no_transcript(db_url: str) -> None:
    async with world(db_url, Worker(heard=Transcribed("speech", 6.0, ()))) as w:
        before = await w.pieces()
        got = await w.transcribe(piece_id=w.clip)
        assert got.is_error and got.content.startswith("nothing_said:") and await w.pieces() == before


@sync
async def test_transcribing_what_is_not_a_recording_or_with_a_bad_language_asks_nothing(db_url: str) -> None:
    async with world(db_url) as w:
        for args in ({"piece_id": w.note}, {"piece_id": w.subs}, {"piece_id": w.clip, "language": "english!"},
                     {"piece_id": w.clip, "language": 4}, {"piece_id": w.clip, "extra": 1}):
            assert (await w.transcribe(**args)).is_error, args
        assert w.worker.transcripts_asked == []


@sync
async def test_a_recording_with_no_sound_or_too_long_says_so_and_adds_nothing(db_url: str) -> None:
    for reason, said in (("no_audio", "no sound"), ("too_long", "minutes of sound"), ("no_speech_service", "no speech service")):
        async with world(db_url, Worker(fails=reason)) as w:
            before = await w.pieces()
            got = await w.transcribe(piece_id=w.clip)
            assert got.is_error and said in got.content and await w.pieces() == before


@sync
async def test_the_tools_are_offered_only_with_a_store_and_a_worker(db_url: str) -> None:
    async with world(db_url) as w:
        names = [s.name for s in (await w.tools().catalogue()).specs]
        assert names == ["bench_frames", "bench_transcribe"]
        assert [s.reads for s in (await w.tools().catalogue()).specs] == [True, False]
        w.worker.can = False
        assert (await w.tools().catalogue()).specs == ()
        w.worker.can = True
        services.register(ObjectStore, NullStore())
        assert (await w.tools().catalogue()).specs == ()


@sync
async def test_the_log_names_ids_and_counts_and_never_the_words_or_the_picture(db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("INFO", logger="ashley.tools")
    async with world(db_url) as w:
        await w.frames(piece_id=w.clip, at=[1, 2])
        await w.transcribe(piece_id=w.clip)
    text = "\n".join(f"{r.getMessage()} {getattr(r, 'fields', {})}" for r in caplog.records)
    assert "'frames': 2" in text and "'segments': 2" in text and "'source': 'speech'" in text
    assert "so it goes" not in text and "hello" not in text and str(PNG) not in text
