"""Shared pieces of the files blind contract tests: an object store written against the `ObjectStore` interface alone
(it can be taken down, made to fail one call kind, and counts its calls), payloads of each file type, the shipped
config, the real Workshop on a throwaway database with that store registered, and the real app with a person signed in."""

import asyncio
import hashlib
from collections.abc import AsyncGenerator, Coroutine, Generator, Mapping
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, TypeVar

import pytest
from ashley import services
from ashley.api.person import person_signed_in, person_uploading
from ashley.db.pool import PoolDatabase
from ashley.files import config as files_config
from ashley.files.config import FilesConfig
from ashley.files.store import ObjectStore, StoreUnavailable
from ashley.live.live import Live
from ashley.main import create_app
from ashley.people.model import Person
from ashley.settings import Settings
from ashley.signin.model import SignedIn
from ashley.workshop import rules as workshop_rules
from ashley.workshop.model import By, Owner
from ashley.workshop.postgres import PostgresWorkshop
from ashley.workshop.workshop import Workshop
from contract.conversations_support import household, person
from fastapi.testclient import TestClient
from httpx2 import Response
from live_support import FakeLive

T = TypeVar("T")


def go(scenario: Coroutine[Any, Any, T], limit: float = 25.0) -> T:
    """`run` that gives back what the coroutine returned."""
    async def bounded() -> T:
        return await asyncio.wait_for(scenario, limit)

    return asyncio.run(bounded())


CONFIG: FilesConfig = files_config.load()
PUBLIC = "https://ashley.test"
LINK_KEY = "k" * 40
PNG = bytes.fromhex("89504e470d0a1a0a") + b"\x00\x00\x00\rIHDRrest"
JPEG = bytes.fromhex("ffd8ff") + b"\xe0\x00\x10JFIF\x00data"
GIF87 = b"GIF87a" + b"\x01\x00\x01\x00"
GIF89 = b"GIF89a" + b"\x01\x00\x01\x00"
WEBP = b"RIFF\x24\x00\x00\x00WEBPVP8 data"
PDF = b"%PDF-1.7\n1 0 obj\n"
ZIP = b"PK\x03\x04" + b"\x14\x00\x00\x00rest"
TEXT = "plain words, a naïve café\nand a second line\n".encode()
SIGNED: dict[str, bytes] = {"image/png": PNG, "image/jpeg": JPEG, "image/gif": GIF89, "image/webp": WEBP,
                            "application/pdf": PDF, "application/zip": ZIP}
HTML = b"<!DOCTYPE html><html><body><script>alert(1)</script></body></html>"
SVG = b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def log_text(caplog: pytest.LogCaptureFixture) -> str:
    """Every captured record as its event and its structured fields, which `caplog.text` leaves out."""
    return "\n".join(f"{r.getMessage()} {getattr(r, 'fields', {})!r}" for r in caplog.records)


def fields_of(caplog: pytest.LogCaptureFixture, event: str) -> list[dict[str, object]]:
    return [dict(getattr(r, "fields", {})) for r in caplog.records if r.getMessage() == event]


class Calls:
    """What an ObjectStore double was asked, in order, as (verb, key)."""

    def __init__(self) -> None:
        self.log: list[tuple[str, str]] = []

    def of(self, verb: str) -> list[str]:
        return [k for v, k in self.log if v == verb]


class FakeStore(ObjectStore):
    """A store that holds bytes in a dict. `down` fails every call; `fail` names verbs (`put`, `get`, `keys`) that fail."""

    def __init__(self, name: str = "s", down: bool = False, fail: frozenset[str] = frozenset()) -> None:
        self.name = name
        self.held: dict[str, bytes] = {}
        self.down = down
        self.fail = fail
        self.calls = Calls()

    def _reach(self, verb: str, key: str) -> None:
        self.calls.log.append((verb, key))
        if self.down or verb in self.fail:
            raise StoreUnavailable(f"{self.name} unreachable")

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


@dataclass(frozen=True)
class World:
    url: str
    alana: Owner
    sam: Owner
    zed: Owner


def world(url: str) -> World:
    h1, h2 = household(url, "one"), household(url, "two")
    return World(url, Owner(h1, person(url, h1, "Alana")), Owner(h1, person(url, h1, "Sam")),
                 Owner(h2, person(url, h2, "Zed")))


def by(owner: Owner) -> By:
    return By(owner.person_id)


@dataclass
class Env:
    world: World
    workshop: Workshop
    store: FakeStore
    live: FakeLive = field(default_factory=FakeLive)


@asynccontextmanager
async def env(url: str, store: ObjectStore | None = None) -> AsyncGenerator[Env]:
    """The real Postgres Workshop with `store` (a FakeStore by default) registered as the object store."""
    db = PoolDatabase(url)
    await db.open()
    live = FakeLive()
    workshop = PostgresWorkshop(db, workshop_rules.load())
    fake = store if store is not None else FakeStore()
    services.register(Live, live)
    services.register(Workshop, workshop)
    services.register(ObjectStore, fake)
    try:
        yield Env(world(url), workshop, fake if isinstance(fake, FakeStore) else FakeStore(), live)
    finally:
        for interface in (Live, Workshop, ObjectStore):
            services.unregister(interface)
        await db.close()


@dataclass
class Rig:
    client: TestClient
    w: World
    store: FakeStore
    who: list[str] = field(default_factory=lambda: ["alana"])

    def as_(self, name: str) -> None:
        self.who[0] = name

    def upload(self, bench_id: int, data: bytes, name: str = "a.bin", declared: str = "",
               content_type: str = "application/octet-stream") -> Response:
        headers = {"content-type": content_type, "x-file-name": name}
        if declared:
            headers["x-file-type"] = declared
        return self.client.post(f"/api/benches/{bench_id}/files", content=data, headers=headers)

    def new_bench(self, title: str = "b") -> int:
        got = self.client.post("/api/benches", json={"title": title})
        assert got.status_code == 200
        return int(got.json()["id"])

    def bench(self, bench_id: int) -> dict[str, Any]:
        got = self.client.get(f"/api/benches/{bench_id}")
        assert got.status_code == 200
        body: dict[str, Any] = got.json()
        return body


@contextmanager
def rig(url: str, store: FakeStore | None = None, signed_in: bool = True) -> Generator[Rig]:
    """The real app, with `store` registered after the app wired its own (none here: no endpoints are configured)."""
    w = world(url)
    settings = Settings(database_url=url, build_version="t", public_url=PUBLIC, files_endpoints="http://nas.test:1",
                        files_bucket="b", files_access_key="a", files_secret_key="s", files_link_key=LINK_KEY)
    app = create_app(settings)
    made = Rig(TestClient(app, base_url=PUBLIC, headers={"origin": PUBLIC}), w, store if store is not None else FakeStore())
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
