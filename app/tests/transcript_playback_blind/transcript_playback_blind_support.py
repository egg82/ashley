"""Shared pieces of the transcript playback blind contract tests: a media worker double written against the `Media`
interface alone (the only fake besides the object store), the real Workshop on a throwaway database with a real
conversation and person turn and the tools built for a turn, and the real app with a person signed in."""

import asyncio
import hashlib
import json
from collections.abc import AsyncGenerator, Coroutine, Generator, Mapping
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, TypeVar

from ashley import services
from ashley.api.person import person_signed_in, person_uploading
from ashley.conversations.conversations import Conversations
from ashley.conversations.model import NewTurn
from ashley.conversations.postgres import PostgresConversations
from ashley.db.pool import PoolDatabase
from ashley.files.store import ObjectStore
from ashley.inference.model import ToolCall, ToolResult
from ashley.live.live import Live
from ashley.looks.looks import Looks
from ashley.looks.postgres import PostgresLooks
from ashley.main import create_app
from ashley.people.model import Person
from ashley.runs.captions import Segment
from ashley.runs.media import Media, MediaUnavailable, Sheet, Source, Transcribed
from ashley.settings import Settings
from ashley.signin.model import SignedIn
from ashley.tools.bench_media import BenchMediaTools
from ashley.workshop import rules as workshop_rules
from ashley.workshop.bench_file import add_file
from ashley.workshop.model import By, Owner, Piece
from ashley.workshop.postgres import PostgresWorkshop
from ashley.workshop.workshop import Workshop
from contract.conversations_support import POLICY, household, person
from fastapi.testclient import TestClient
from live_support import FakeLive

T = TypeVar("T")

RULES = workshop_rules.load()
PUBLIC = "https://ashley.test"


def go(scenario: Coroutine[Any, Any, T], limit: float = 25.0) -> T:
    async def bounded() -> T:
        return await asyncio.wait_for(scenario, limit)

    return asyncio.run(bounded())


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


MP4 = b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00" + b"\x00" * 8 + b"mdat-payload"
MP3 = b"ID3\x04\x00\x00\x00\x00\x00\x00mp3-payload"
JPEG = bytes.fromhex("ffd8ff") + b"\xe0\x00\x10JFIF\x00sheet-bytes"


def said(*lines: tuple[float, str], source: str = "speech") -> Transcribed:
    kind: Any = source
    return Transcribed(kind, 60.0, tuple(Segment(s, t) for s, t in lines))


class FakeStore(ObjectStore):
    """A dict of bytes."""

    def __init__(self) -> None:
        self.held: dict[str, bytes] = {}

    async def put(self, key: str, data: bytes) -> int:
        self.held[key] = data
        return 1

    async def get(self, key: str) -> bytes | None:
        return self.held.get(key)

    async def keys(self, prefix: str) -> frozenset[str]:
        return frozenset(k for k in self.held if k.startswith(prefix))

    async def delete(self, key: str) -> None:
        self.held.pop(key, None)

    async def listing(self, prefix: str) -> Mapping[str, datetime]:
        return {k: datetime.now(UTC) for k in self.held if k.startswith(prefix)}


class FakeMedia(Media):
    """The media worker: `words_to_give` is what the next transcription brings back (an exception is raised)."""

    def __init__(self) -> None:
        self.words_to_give: Transcribed | MediaUnavailable = said((0, "hello"))

    def available(self) -> bool:
        return True

    async def frames(self, name: str, source: Source, at: tuple[float, ...]) -> Sheet:
        return Sheet(JPEG, len(at), 12.0)

    async def transcribe(self, name: str, source: Source, language: str | None) -> Transcribed:
        if isinstance(self.words_to_give, MediaUnavailable):
            raise self.words_to_give
        return self.words_to_give

    async def youtube_captions(self, name: str, video_id: str) -> Transcribed:
        raise MediaUnavailable("not_wired")


@dataclass
class Scene:
    workshop: Workshop
    media: FakeMedia
    alana: Owner
    bench: int
    conversation: int
    turn: int

    def tools(self) -> BenchMediaTools:
        return BenchMediaTools(self.alana.household_id, self.alana.person_id, self.bench, self.conversation, self.turn)

    async def put(self, data: bytes, name: str) -> Piece:
        await add_file(self.alana, self.bench, By(self.alana.person_id), data, name, "", RULES)
        return (await self.workshop.read(self.alana, self.bench)).pieces[-1]

    async def pieces(self) -> tuple[Piece, ...]:
        return (await self.workshop.read(self.alana, self.bench)).pieces

    async def transcribe(self, clip: Piece, *lines: tuple[float, str]) -> ToolResult:
        self.media.words_to_give = said(*lines)
        return await self.tools().call(ToolCall("c1", "bench_transcribe", {"piece_id": clip.id}))


@asynccontextmanager
async def scene(url: str) -> AsyncGenerator[Scene]:
    db = PoolDatabase(url)
    await db.open()
    workshop = PostgresWorkshop(db, RULES)
    conversations: Conversations = PostgresConversations(db, POLICY)
    media = FakeMedia()
    h = household(url, "one")
    alana = Owner(h, person(url, h, "Alana"))
    services.register(Live, FakeLive())
    services.register(Workshop, workshop)
    services.register(ObjectStore, FakeStore())
    services.register(Media, media)
    services.register(Looks, PostgresLooks(db))
    try:
        bench = (await workshop.open(alana, "b")).id
        conversation = await conversations.start(h, "chat", [alana.person_id])
        turn = await conversations.add_turn(conversation.id, NewTurn("person", "listen", speaker_id=alana.person_id))
        yield Scene(workshop, media, alana, bench, conversation.id, turn.id)
    finally:
        for interface in (Live, Workshop, ObjectStore, Media, Looks):
            services.unregister(interface)
        await db.close()


def wire_piece(pieces: list[dict[str, Any]], piece_id: int) -> dict[str, Any]:
    (found,) = [p for p in pieces if p["id"] == piece_id]
    return found


@dataclass
class Rig:
    """The real app with Alana signed in."""

    client: TestClient

    def bench(self) -> int:
        got = self.client.post("/api/benches", json={"title": "b"})
        assert got.status_code == 200
        return int(got.json()["id"])

    def command(self, bench: int, **body: object) -> dict[str, Any]:
        got = self.client.post(f"/api/benches/{bench}/commands", json=body)
        assert got.status_code == 200, got.text
        out: dict[str, Any] = got.json()
        return out

    def add_reader(self, bench: int, body: str, title: str = "t") -> int:
        done = self.command(bench, type="add", kind="reader", title=title, body=body, size="medium")
        assert done.get("piece_id") is not None, done
        return int(done["piece_id"])

    def pieces(self, bench: int) -> list[dict[str, Any]]:
        got = self.client.get(f"/api/benches/{bench}")
        assert got.status_code == 200
        found: list[dict[str, Any]] = got.json()["pieces"]
        return found


@contextmanager
def rig(url: str) -> Generator[Rig]:
    h = household(url, "one")
    alana = Owner(h, person(url, h, "Alana"))
    settings = Settings(database_url=url, build_version="t", public_url=PUBLIC, files_endpoints="http://nas.test:1",
                        files_bucket="b", files_access_key="a", files_secret_key="s", files_link_key="k" * 40)
    app = create_app(settings)
    me = SignedIn(1, Person(alana.person_id, h, "Alana"))
    app.dependency_overrides[person_signed_in] = lambda: me
    app.dependency_overrides[person_uploading] = lambda: me
    with TestClient(app, base_url=PUBLIC, headers={"origin": PUBLIC}) as client:
        services.register(ObjectStore, FakeStore())
        services.register(Live, FakeLive())
        yield Rig(client)
    services.unregister(ObjectStore)
    services.unregister(Live)


def raw_body(recording: object, text: str = "a\nb", url: str = "", title: str = "") -> str:
    """A reader body written by hand (the documented JSON object), `recording` as given."""
    return json.dumps({"url": url, "title": title, "text": text, "recording": recording})
