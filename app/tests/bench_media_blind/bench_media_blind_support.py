"""Shared pieces of the bench video/audio blind contract tests: recordings of each signed type, a Media worker double
written against the `Media` interface alone (it answers what it is told to, or fails with a reason, and records what it
was asked), an object store double, and a scene: the real Workshop and Looks on a throwaway database with a real
conversation and person turn, the double store and worker registered, and the tools built for a turn."""

import asyncio
import hashlib
import itertools
import json
from collections.abc import AsyncGenerator, Callable, Coroutine, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, TypeVar

import psycopg
import pytest
from ashley import services
from ashley.conversations.conversations import Conversations
from ashley.conversations.model import NewTurn
from ashley.conversations.postgres import PostgresConversations
from ashley.db.pool import PoolDatabase
from ashley.files import config as files_config
from ashley.files.store import ObjectStore, StoreUnavailable
from ashley.inference.model import ToolCall, ToolResult
from ashley.live.live import Live
from ashley.looks import config as looks_config
from ashley.looks.looks import Looks
from ashley.looks.postgres import PostgresLooks
from ashley.runs import media_config
from ashley.runs.captions import Segment
from ashley.runs.media import Media, MediaUnavailable, Sheet, Source, Transcribed
from ashley.tools.bench_media import BenchMediaTools
from ashley.workshop import rules as workshop_rules
from ashley.workshop.bench_file import add_file
from ashley.workshop.model import By, Owner, Piece
from ashley.workshop.postgres import PostgresWorkshop
from ashley.workshop.workshop import Workshop
from contract.conversations_support import POLICY, household, person
from live_support import FakeLive
from look_pictures_support import noise

T = TypeVar("T")

RULES = workshop_rules.load()
FILES = files_config.load()
LOOKS = looks_config.load()
MEDIA = media_config.load()


def go(scenario: Coroutine[Any, Any, T], limit: float = 25.0) -> T:
    async def bounded() -> T:
        return await asyncio.wait_for(scenario, limit)

    return asyncio.run(bounded())


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def ftyp(brand: bytes) -> bytes:
    return b"\x00\x00\x00\x18ftyp" + brand + b"\x00\x00\x02\x00" + b"\x00" * 8 + b"mdat-payload"


MP4 = ftyp(b"isom")
QUICKTIME = ftyp(b"qt  ")
WEBM = bytes.fromhex("1a45dfa3") + b"\x9fB\x86\x81\x01webm-payload"
M4A = ftyp(b"M4A ")
MP3 = b"ID3\x04\x00\x00\x00\x00\x00\x00mp3-payload"
OGG = b"OggS\x00\x02" + b"\x00" * 8 + b"ogg-payload"
WAV = b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x10\x00\x00\x00"
FLAC = b"fLaC\x00\x00\x00\x22" + b"\x00" * 20
WEBP = b"RIFF\x24\x00\x00\x00WEBPVP8 data"
PNG = noise((64, 48))
PDF = b"%PDF-1.7\n1 0 obj\n"
JPEG = bytes.fromhex("ffd8ff") + b"\xe0\x00\x10JFIF\x00sheet-bytes"

SRT = "1\n00:00:01,000 --> 00:00:03,000\nhello there\n\n2\n00:01:05,500 --> 00:01:07,000\nsecond line\n"
VTT = "WEBVTT\n\n00:01.000 --> 00:03.000\nhello there\n\n01:05.500 --> 01:07.000\nsecond line\n"
SRT_LINES = "[0:01] hello there\n[1:05] second line"

_ids = itertools.count(1)


def call(tool: str, /, **args: object) -> ToolCall:
    return ToolCall(f"c{next(_ids)}", tool, args)


def sheet(count: int = 1, jpeg: bytes = JPEG, duration_s: float = 12.0) -> Sheet:
    return Sheet(jpeg, count, duration_s)


def said(*lines: tuple[float, str], source: str = "speech", duration_s: float = 60.0) -> Transcribed:
    kind: Any = source
    return Transcribed(kind, duration_s, tuple(Segment(s, t) for s, t in lines))


class FakeStore(ObjectStore):
    """A dict of bytes. `fail` names verbs (`put`, `get`, `keys`, `delete`, `listing`) that raise StoreUnavailable."""

    def __init__(self) -> None:
        self.held: dict[str, bytes] = {}
        self.fail: frozenset[str] = frozenset()
        self.log: list[tuple[str, str]] = []

    def _reach(self, verb: str, key: str) -> None:
        self.log.append((verb, key))
        if verb in self.fail:
            raise StoreUnavailable("down")

    def puts(self) -> list[str]:
        return [k for v, k in self.log if v == "put"]

    async def put(self, key: str, data: bytes) -> int:
        self._reach("put", key)
        self.held[key] = data
        return 1

    async def get(self, key: str) -> bytes | None:
        self._reach("get", key)
        return self.held.get(key)

    async def keys(self, prefix: str) -> frozenset[str]:
        self._reach("keys", prefix)
        return frozenset(k for k in self.held if k.startswith(prefix))

    async def delete(self, key: str) -> None:
        self._reach("delete", key)
        self.held.pop(key, None)

    async def listing(self, prefix: str) -> Mapping[str, datetime]:
        self._reach("listing", prefix)
        return {k: datetime.now(UTC) for k in self.held if k.startswith(prefix)}


Frames = Sheet | MediaUnavailable | Callable[[], Sheet]
Words = Transcribed | MediaUnavailable


class FakeMedia(Media):
    """The media worker: `sheet_to_give` and `words_to_give` are what the next jobs bring back (an exception is raised)."""

    def __init__(self) -> None:
        self.sheet_to_give: Sheet | MediaUnavailable = sheet()
        self.words_to_give: Transcribed | MediaUnavailable = said((0, "hello"))
        self.frame_jobs: list[tuple[str, Source, tuple[float, ...]]] = []
        self.transcribe_jobs: list[tuple[str, Source, str | None]] = []

    def available(self) -> bool:
        return True

    async def frames(self, name: str, source: Source, at: tuple[float, ...]) -> Sheet:
        self.frame_jobs.append((name, source, at))
        if isinstance(self.sheet_to_give, MediaUnavailable):
            raise self.sheet_to_give
        return self.sheet_to_give

    async def transcribe(self, name: str, source: Source, language: str | None) -> Transcribed:
        self.transcribe_jobs.append((name, source, language))
        if isinstance(self.words_to_give, MediaUnavailable):
            raise self.words_to_give
        return self.words_to_give

    async def youtube_captions(self, name: str, video_id: str) -> Transcribed:
        raise MediaUnavailable("not_wired")

    def jobs(self) -> int:
        return len(self.frame_jobs) + len(self.transcribe_jobs)


@dataclass
class Scene:
    url: str
    db: PoolDatabase
    workshop: Workshop
    store: FakeStore
    media: FakeMedia
    live: FakeLive
    alana: Owner
    other: Owner
    bench: int
    conversation: int
    turn: int
    conversations: Conversations
    looks: Looks
    caught: list[int] = field(default_factory=lambda: [])

    def tools(self, turn: int | None = None, bench: int | None = None) -> BenchMediaTools:
        return BenchMediaTools(self.alana.household_id, self.alana.person_id, self.bench if bench is None else bench,
                               self.conversation, self.turn if turn is None else turn)

    async def new_turn(self) -> int:
        made = await self.conversations.add_turn(self.conversation, NewTurn("person", "again", speaker_id=self.alana.person_id))
        return made.id

    async def put(self, data: bytes, name: str, bench: int | None = None) -> Piece:
        """A file piece made the way an upload makes one; the last piece of the bench."""
        number = self.bench if bench is None else bench
        await add_file(self.alana, number, By(self.alana.person_id), data, name, "", RULES)
        return (await self.workshop.read(self.alana, number)).pieces[-1]

    async def pieces(self, bench: int | None = None) -> tuple[Piece, ...]:
        return (await self.workshop.read(self.alana, self.bench if bench is None else bench)).pieces

    async def log_size(self, bench: int | None = None) -> int:
        return len(await self.workshop.log(self.alana, self.bench if bench is None else bench))

    def rows(self, query: str, params: tuple[object, ...] = ()) -> list[tuple[Any, ...]]:
        with psycopg.connect(self.url, autocommit=True) as conn:
            return conn.execute(query.encode(), params).fetchall()

    def looks_of(self, turn: int | None = None) -> list[tuple[Any, ...]]:
        return self.rows("SELECT call_id, bench_id, piece_id, sha256, media_type, size FROM bench_looks WHERE turn_id = %s ORDER BY id",
                         (self.turn if turn is None else turn,))


@asynccontextmanager
async def scene(url: str) -> AsyncGenerator[Scene]:
    db = PoolDatabase(url)
    await db.open()
    live = FakeLive()
    workshop = PostgresWorkshop(db, RULES)
    looks = PostgresLooks(db)
    conversations = PostgresConversations(db, POLICY)
    store, media = FakeStore(), FakeMedia()
    spare_home = household(url, "zero")
    person(url, spare_home, "Nobody")
    person(url, spare_home, "Nobody else")
    h = household(url, "one")
    alana = Owner(h, person(url, h, "Alana"))
    other = Owner(h, person(url, h, "Sam"))
    services.register(Live, live)
    services.register(Workshop, workshop)
    services.register(ObjectStore, store)
    services.register(Media, media)
    services.register(Looks, looks)
    try:
        bench = (await workshop.open(alana, "b")).id
        spare = await conversations.start(h, "chat", [alana.person_id])
        for _ in range(3):
            await conversations.add_turn(spare.id, NewTurn("person", "earlier", speaker_id=alana.person_id))
        conversation = await conversations.start(h, "chat", [alana.person_id])
        turn = await conversations.add_turn(conversation.id, NewTurn("person", "look", speaker_id=alana.person_id))
        yield Scene(url, db, workshop, store, media, live, alana, other, bench, conversation.id, turn.id, conversations, looks)
    finally:
        for interface in (Live, Workshop, ObjectStore, Media, Looks):
            services.unregister(interface)
        await db.close()


def body(result: ToolResult) -> Any:
    return json.loads(result.content)


def fields_of(caplog: pytest.LogCaptureFixture, event: str) -> list[dict[str, object]]:
    return [dict(getattr(r, "fields", {})) for r in caplog.records if r.getMessage() == event]


def log_text(caplog: pytest.LogCaptureFixture) -> str:
    return "\n".join(f"{r.getMessage()} {getattr(r, 'fields', {})!r}" for r in caplog.records)


PUBLIC = "https://ashley.test"
LINK_KEY = "k" * 40


@dataclass
class Rig:
    """The real app with Alana signed in and the double store registered."""

    client: Any
    owner: Owner
    store: FakeStore
    live: FakeLive

    def new_bench(self) -> int:
        got = self.client.post("/api/benches", json={"title": "b"})
        assert got.status_code == 200
        return int(got.json()["id"])

    def upload(self, bench_id: int, data: bytes, name: str, declared: str = "") -> Any:
        headers = {"content-type": "application/octet-stream", "x-file-name": name}
        if declared:
            headers["x-file-type"] = declared
        return self.client.post(f"/api/benches/{bench_id}/files", content=data, headers=headers)

    def pieces(self, bench_id: int) -> list[dict[str, Any]]:
        got = self.client.get(f"/api/benches/{bench_id}")
        assert got.status_code == 200
        found: list[dict[str, Any]] = got.json()["pieces"]
        return found


def rig(url: str) -> Any:
    from contextlib import contextmanager

    from ashley.api.person import person_signed_in, person_uploading
    from ashley.main import create_app
    from ashley.people.model import Person
    from ashley.settings import Settings
    from ashley.signin.model import SignedIn
    from fastapi.testclient import TestClient

    @contextmanager
    def made() -> Any:
        h = household(url, "one")
        alana = Owner(h, person(url, h, "Alana"))
        settings = Settings(database_url=url, build_version="t", public_url=PUBLIC, files_endpoints="http://nas.test:1",
                            files_bucket="b", files_access_key="a", files_secret_key="s", files_link_key=LINK_KEY)
        app = create_app(settings)
        store, live = FakeStore(), FakeLive()
        me = SignedIn(1, Person(alana.person_id, h, "Alana"))
        app.dependency_overrides[person_signed_in] = lambda: me
        app.dependency_overrides[person_uploading] = lambda: me
        services.register(Live, live)
        services.register(ObjectStore, store)
        with TestClient(app, base_url=PUBLIC, headers={"origin": PUBLIC}) as client:
            services.register(ObjectStore, store)
            services.register(Live, live)
            yield Rig(client, alana, store, live)
        services.unregister(ObjectStore)
        services.unregister(Live)

    return made()


async def take(s: Scene, clip: int, turn: int | None = None, call_: ToolCall | None = None) -> ToolResult:
    """One `bench_frames` call at one moment of piece `clip`, in `turn`'s tools."""
    return await s.tools(turn).call(call_ or call("bench_frames", piece_id=clip, at=[1]))
