"""Shared pieces of the bench_look blind contract tests: an object store written against the `ObjectStore` interface
alone, a Looker that plays screenshots or failures and records what it was asked, and a scene of the real Workshop,
Looks and Conversations on one throwaway database with the real app and a person who can be switched."""

import asyncio
import hashlib
import io
import random
from collections.abc import AsyncGenerator, Coroutine, Generator, Mapping
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, TypeVar

import pytest
from PIL import Image as PilImage
from ashley import services
from ashley.api.person import person_signed_in, person_uploading
from ashley.conversations.conversations import Conversations
from ashley.conversations.model import NewTurn, Turn
from ashley.conversations.postgres import PostgresConversations
from ashley.db.pool import PoolDatabase
from ashley.files.store import ObjectStore, StoreUnavailable
from ashley.inference.model import ToolCall, ToolResult
from ashley.live.live import Live
from ashley.looks import config as looks_config
from ashley.looks.looker import Looker, LookUnavailable, Shot, Target
from ashley.looks.looks import Look, Looks, LooksUnavailable, NewLook
from ashley.looks.postgres import PostgresLooks
from ashley.main import create_app
from ashley.people.model import Person
from ashley.settings import Settings
from ashley.signin.model import SignedIn
from ashley.tools.bench_look import BenchLookTools
from ashley.workshop import rules as workshop_rules
from ashley.workshop.bench_file import add_file
from ashley.workshop.commands import Add
from ashley.workshop.model import By, Owner, Text
from ashley.workshop.postgres import PostgresWorkshop
from ashley.workshop.workshop import Workshop
from contract.conversations_support import POLICY, household, person
from fastapi.testclient import TestClient
from live_support import FakeLive

T = TypeVar("T")

CONFIG = looks_config.load()
PUBLIC = "https://ashley.test"
LINK_KEY = "k" * 40


def picture(fmt: str = "PNG", size: tuple[int, int] = (64, 48)) -> bytes:
    """A real picture of `size` in format `fmt`, noisy so no format squeezes it to nothing."""
    out = io.BytesIO()
    PilImage.frombytes("RGB", size, random.Random(1).randbytes(size[0] * size[1] * 3)).save(out, fmt)
    return out.getvalue()


PNG = picture()
JPEG = bytes.fromhex("ffd8ff") + b"\xe0\x00\x10JFIF\x00data"
SHOT_BYTES = bytes.fromhex("ffd8ff") + b"\xe0\x00\x10JFIF\x00screenshot"
PDF = b"%PDF-1.7\n1 0 obj\n"
_n = iter(range(1, 1_000_000))


def go(scenario: Coroutine[Any, Any, T], limit: float = 25.0) -> T:
    async def bounded() -> T:
        return await asyncio.wait_for(scenario, limit)

    return asyncio.run(bounded())


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fields_of(caplog: pytest.LogCaptureFixture, event: str) -> list[dict[str, object]]:
    return [dict(getattr(r, "fields", {})) for r in caplog.records if r.getMessage() == event]


def log_text(caplog: pytest.LogCaptureFixture) -> str:
    return "\n".join(f"{r.getMessage()} {getattr(r, 'fields', {})!r}" for r in caplog.records)


def call(**args: object) -> ToolCall:
    return ToolCall(f"c{next(_n)}", "bench_look", args)


class FakeStore(ObjectStore):
    """Bytes in a dict; `down` fails every call; `fail` names verbs that fail."""

    def __init__(self, down: bool = False, fail: frozenset[str] = frozenset()) -> None:
        self.held: dict[str, bytes] = {}
        self.down = down
        self.fail = fail
        self.log: list[tuple[str, str]] = []

    def _reach(self, verb: str, key: str) -> None:
        self.log.append((verb, key))
        if self.down or verb in self.fail:
            raise StoreUnavailable("unreachable")

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


@dataclass
class FakeLooker(Looker):
    """Plays `shot`, or raises LookUnavailable when `fail` is set; `draws` is whether it says it can draw."""

    shot: bytes = SHOT_BYTES
    fail: str = ""
    draws: bool = True
    asked: list[tuple[str, Target]] = field(default_factory=list[tuple[str, Target]])

    def renders(self) -> bool:
        return self.draws

    async def look(self, name: str, target: Target) -> Shot:
        self.asked.append((name, target))
        if self.fail:
            raise LookUnavailable(self.fail)
        return Shot(self.shot)


class FailingLooks(Looks):
    """Looks whose record cannot be read or written, per verb."""

    def __init__(self, inner: Looks, fail: frozenset[str]) -> None:
        self.inner = inner
        self.fail = fail

    async def keep(self, look: NewLook) -> int:
        if "keep" in self.fail:
            raise LooksUnavailable("down")
        return await self.inner.keep(look)

    async def taken(self, household_id: int, turn_id: int, except_call: str) -> int:
        if "taken" in self.fail:
            raise LooksUnavailable("down")
        return await self.inner.taken(household_id, turn_id, except_call)

    async def in_conversation(self, household_id: int, conversation_id: int) -> list[Look]:
        if "in_conversation" in self.fail:
            raise LooksUnavailable("down")
        return await self.inner.in_conversation(household_id, conversation_id)


@dataclass(frozen=True)
class World:
    url: str
    alana: Owner
    sam: Owner
    zed: Owner


def world(url: str) -> World:
    """Alana and Sam in one household, Zed in another, after a padding household and two padding people, so no
    household id equals a person id."""
    pad = household(url, "pad")
    person(url, pad, "Pad One")
    person(url, pad, "Pad Two")
    h1, h2 = household(url, "one"), household(url, "two")
    return World(url, Owner(h1, person(url, h1, "Alana")), Owner(h1, person(url, h1, "Sam")),
                 Owner(h2, person(url, h2, "Zed")))


def by(owner: Owner) -> By:
    return By(owner.person_id)


def new_look(owner: Owner, conversation: int, turn: int, call_id: str = "c", bench: int = 1, piece: int | None = None,
             data: bytes = SHOT_BYTES, media_type: str = "image/jpeg") -> NewLook:
    return NewLook(owner.household_id, conversation, turn, call_id, bench, piece, sha(data), media_type, len(data))


@dataclass
class Scene:
    w: World
    db: PoolDatabase
    workshop: Workshop
    looks: Looks
    conversations: Conversations
    store: FakeStore
    looker: FakeLooker

    async def bench(self, owner: Owner, title: str = "b") -> int:
        return (await self.workshop.open(owner, title)).id

    async def note(self, owner: Owner, bench: int, title: str = "n", body: str = "hello") -> int:
        applied = await self.workshop.apply(owner, bench, Add(by(owner), "note", Text(title, body), "small"))
        assert applied.piece_id is not None
        return applied.piece_id

    async def image(self, owner: Owner, bench: int, data: bytes = PNG, name: str = "a.png") -> int:
        _, applied = await add_file(owner, bench, by(owner), data, name, "", workshop_rules.load())
        assert applied.piece_id is not None
        return applied.piece_id

    async def asked(self, owner: Owner, text: str = "look", thread: str = "") -> tuple[int, Turn]:
        """A conversation of `owner`'s web thread (or `thread`) with a person turn in it."""
        conv = await self.conversations.for_thread(owner.household_id, thread or f"person:{owner.person_id}:web", "chat",
                                                   [owner.person_id])
        turn = await self.conversations.add_turn(conv.id, NewTurn("person", text, speaker_id=owner.person_id))
        return conv.id, turn

    async def answer(self, conv: int, turn: Turn, text: str = "seen", follows: bool = False) -> Turn:
        return await self.conversations.add_turn(conv, NewTurn("ashley", text, answers=turn.id, follows=follows))

    def tools(self, owner: Owner, bench: int, conv: int, turn: int) -> BenchLookTools:
        return BenchLookTools(owner.household_id, owner.person_id, bench, conv, turn)

    async def look(self, owner: Owner, bench: int, conv: int, turn: int, **args: object) -> ToolResult:
        return await self.tools(owner, bench, conv, turn).call(call(**args))


@asynccontextmanager
async def scene(url: str, store: FakeStore | None = None, looker: FakeLooker | None = None,
                register: bool = True) -> AsyncGenerator[Scene]:
    """The real Postgres Workshop, Looks and Conversations on one pool, with a fake store and a fake Looker, registered
    as the process's services unless `register` is off (a scene that seeds the database of a running app). A padding
    conversation comes first, so no conversation id equals a turn id."""
    db = PoolDatabase(url)
    await db.open()
    made = Scene(world(url), db, PostgresWorkshop(db, workshop_rules.load()), PostgresLooks(db),
                 PostgresConversations(db, POLICY), store if store is not None else FakeStore(),
                 looker if looker is not None else FakeLooker())
    registered: list[tuple[Any, Any]] = [(Live, FakeLive()), (Workshop, made.workshop), (Looks, made.looks),
                                         (Conversations, made.conversations), (ObjectStore, made.store),
                                         (Looker, made.looker)]
    padding = await made.conversations.for_thread(made.w.alana.household_id, "padding", "chat", [])
    for _ in range(3):
        await made.conversations.add_turn(padding.id, NewTurn("person", "padding"))
    if register:
        for interface, implementation in registered:
            services.register(interface, implementation)
    try:
        yield made
    finally:
        if register:
            for interface, _ in registered:
                services.unregister(interface)
        await db.close()


@dataclass
class Rig:
    client: TestClient
    w: World
    store: FakeStore
    url: str
    who: list[str] = field(default_factory=lambda: ["alana"])

    def as_(self, name: str) -> None:
        self.who[0] = name

    def new_bench(self) -> int:
        got = self.client.post("/api/benches", json={"title": "b"})
        assert got.status_code == 200
        return int(got.json()["id"])

    def upload(self, bench_id: int, data: bytes, name: str = "a.png") -> int:
        got = self.client.post(f"/api/benches/{bench_id}/files", content=data,
                               headers={"content-type": "application/octet-stream", "x-file-name": name})
        assert got.status_code == 200, got.text
        return int(got.json()["piece_id"]) if "piece_id" in got.json() else self.pieces(bench_id)[-1]["id"]

    def pieces(self, bench_id: int) -> list[dict[str, Any]]:
        got = self.client.get(f"/api/benches/{bench_id}")
        assert got.status_code == 200
        pieces: list[dict[str, Any]] = got.json()["pieces"]
        return pieces

    def add_note(self, bench_id: int, title: str = "n", body: str = "text") -> int:
        got = self.client.post(f"/api/benches/{bench_id}/commands",
                               json={"type": "add", "kind": "note", "title": title, "body": body, "size": "small"})
        assert got.status_code == 200, got.text
        return int(self.pieces(bench_id)[-1]["id"])

    def conversation(self) -> dict[str, Any]:
        got = self.client.get("/api/chat/conversation")
        assert got.status_code == 200
        body: dict[str, Any] = got.json()
        return body


@contextmanager
def rig(url: str, store: FakeStore | None = None, signed_in: bool = True) -> Generator[Rig]:
    """The real app (link key set) with a fake store registered after the app wired its own."""
    w = world(url)
    settings = Settings(database_url=url, build_version="t", public_url=PUBLIC, files_endpoints="http://nas.test:1",
                        files_bucket="b", files_access_key="a", files_secret_key="s", files_link_key=LINK_KEY)
    app = create_app(settings)
    made = Rig(TestClient(app, base_url=PUBLIC, headers={"origin": PUBLIC}), w, store if store is not None else FakeStore(), url)
    if signed_in:
        owners = {"alana": w.alana, "sam": w.sam, "zed": w.zed}

        def me() -> SignedIn:
            o = owners[made.who[0]]
            return SignedIn(1, Person(o.person_id, o.household_id, made.who[0].capitalize()))

        app.dependency_overrides[person_signed_in] = me
        app.dependency_overrides[person_uploading] = me
    services.register(Live, FakeLive())
    services.register(ObjectStore, made.store)
    with made.client:
        services.register(ObjectStore, made.store)
        yield made
    services.unregister(ObjectStore)

