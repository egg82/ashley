"""Support for the blind run-artifact and model-report tests: payloads of each mesh type (and the files that only look
like one), an object store written against the `ObjectStore` interface alone, a fake Sandbox that plays outputs, the
real Workshop, Runs and Postgres on a throwaway database, and the real app with a person signed in."""

import asyncio
import hashlib
import io
import json
import struct
import zipfile
from collections.abc import AsyncGenerator, Coroutine, Generator, Mapping, Sequence
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, TypeVar

import pytest
from ashley import services
from ashley.api.person import person_signed_in
from ashley.db.database import Database
from ashley.db.pool import PoolDatabase
from ashley.files import config as files_config
from ashley.files.config import FilesConfig
from ashley.files.store import ObjectStore, StoreUnavailable
from ashley.live.events import Event, Watcher
from ashley.live.fanout import Subscription
from ashley.live.live import Live
from ashley.main import create_app
from ashley.people.model import Person
from ashley.runs.model import Job, Language, NewRun, Output
from ashley.runs.postgres import PostgresRuns
from ashley.runs.runs import Runs
from ashley.runs.sandbox import Sandbox, SandboxUnavailable
from ashley.settings import Settings
from ashley.signin.model import SignedIn
from ashley.workshop import rules as workshop_rules
from ashley.workshop.commands import Add, Archive, Run
from ashley.workshop.model import By, Owner, Text
from ashley.workshop.postgres import PostgresWorkshop
from ashley.workshop.rules import Rules
from ashley.workshop.workshop import Workshop
from contract.conversations_support import household, person
from fastapi.testclient import TestClient

T = TypeVar("T")

PUBLIC = "https://ashley.test"
LINK_KEY = "k" * 40
CONFIG: FilesConfig = files_config.load()
CAD: Language = "build123d"
GLB_NAME, STL_NAME, MF_NAME, REPORT_NAME = "out/model.glb", "out/model.stl", "out/model.3mf", "out/report.json"


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


def glb(extra: bytes = b"") -> bytes:
    """A binary glTF: the `glTF` magic, version 2, a length, then `extra`."""
    return b"glTF" + struct.pack("<I", 2) + struct.pack("<I", 12 + len(extra)) + extra


def glb_version(version: int) -> bytes:
    return b"glTF" + struct.pack("<I", version) + struct.pack("<I", 12)


def stl(triangles: int = 1, extra: int = 0, seed: int = 0) -> bytes:
    """A binary STL: an 80 byte header, the triangle count, 50 bytes a triangle, and `extra` stray bytes at the end."""
    body = bytes((seed + i) % 251 + 1 for i in range(50 * triangles)) if triangles else b""
    return b"\x00" * 80 + struct.pack("<I", triangles) + body + b"\x00" * extra


def stl_claiming(count: int, triangles: int) -> bytes:
    """A binary STL whose header says `count` triangles while it holds `triangles`."""
    return b"\x00" * 80 + struct.pack("<I", count) + b"\x01" * (50 * triangles)


ASCII_STL = b"solid cube\n facet normal 0 0 1\n  outer loop\n   vertex 0 0 0\n   vertex 1 0 0\n   vertex 0 1 0\n  endloop\n" \
            b" endfacet\nendsolid cube\n"


def zipped(members: Mapping[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def threemf(seed: str = "a") -> bytes:
    return zipped({"[Content_Types].xml": b"<Types/>", "3D/3dmodel.model": f"<model>{seed}</model>".encode()})


PNG = bytes.fromhex("89504e470d0a1a0a") + b"\x00\x00\x00\rIHDRrest"
GOOD: dict[str, bytes] = {GLB_NAME: glb(b"one"), STL_NAME: stl(2), MF_NAME: threemf()}
TYPES: dict[str, str] = {GLB_NAME: "model/gltf-binary", STL_NAME: "model/stl", MF_NAME: "model/3mf"}


class Calls:
    def __init__(self) -> None:
        self.log: list[tuple[str, str]] = []

    def of(self, verb: str) -> list[str]:
        return [k for v, k in self.log if v == verb]


class Site(ObjectStore):
    """A store that holds bytes in a dict, stamped with a settable time. `down` fails every call; `puts_allowed` is how
    many writes succeed before every later one fails; `no_delete` fails deletes."""

    def __init__(self, name: str = "s") -> None:
        self.name = name
        self.held: dict[str, bytes] = {}
        self.written: dict[str, datetime] = {}
        self.now = datetime(2030, 1, 1, tzinfo=UTC)
        self.down = False
        self.puts_allowed: int | None = None
        self.calls = Calls()

    def _reach(self, verb: str, key: str) -> None:
        self.calls.log.append((verb, key))
        if self.down:
            raise StoreUnavailable(f"{self.name} unreachable")

    async def put(self, key: str, data: bytes) -> int:
        self._reach("put", key)
        if self.puts_allowed is not None:
            if self.puts_allowed <= 0:
                raise StoreUnavailable(f"{self.name} refused a write")
            self.puts_allowed -= 1
        self.held[key] = data
        self.written[key] = self.now
        return 1

    async def get(self, key: str) -> bytes | None:
        self._reach("get", key)
        return self.held.get(key)

    async def delete(self, key: str) -> None:
        self._reach("delete", key)
        self.held.pop(key, None)
        self.written.pop(key, None)

    async def listing(self, prefix: str) -> Mapping[str, datetime]:
        self._reach("listing", prefix)
        return {k: self.written[k] for k in self.held if k.startswith(prefix)}

    async def keys(self, prefix: str) -> frozenset[str]:
        return frozenset(await self.listing(prefix))


def ran(files: Mapping[str, str] | None = None, artifacts: Mapping[str, bytes] | None = None, skipped: tuple[str, ...] = (),
        stdout: str = "") -> Output:
    return Output("ran", 0, stdout, "", False, dict(files or {}), skipped, dict(artifacts or {}))


@dataclass
class Box(Sandbox):
    """Plays `outputs` in turn (the last repeats) and keeps its jobs; `down` makes it unable to run anything."""

    outputs: list[Output] = field(default_factory=lambda: [ran()])
    jobs: list[Job] = field(default_factory=lambda: list[Job]())
    down: bool = False

    def languages(self) -> tuple[Language, ...]:
        return ("python", "build123d")

    async def run(self, job: Job) -> Output:
        self.jobs.append(job)
        if self.down:
            raise SandboxUnavailable("down")
        return self.outputs[min(len(self.jobs) - 1, len(self.outputs) - 1)]


class Quiet(Live):
    def publish(self, event: Event) -> None:
        return None

    def subscribe(self, viewer: Watcher) -> Subscription:
        raise NotImplementedError


def measurement(name: str, value: float, source: str = "measured", unit: str = "mm") -> dict[str, object]:
    return {"name": name, "value": value, "unit": unit, "source": source}


def facts_body(*items: Mapping[str, object]) -> str:
    return json.dumps({"items": list(items)})


def check_json(name: str = "c", actual: float = 2.0, op: str = ">=", target: float = 1.5, tolerance: float = 0.0,
               rests_on: Sequence[str] = ()) -> dict[str, object]:
    return {"name": name, "actual": actual, "op": op, "target": target, "tolerance": tolerance, "rests_on": list(rests_on)}


def part_json(name: str = "part1") -> dict[str, object]:
    return {"name": name, "volume": 6000.0, "bbox": {"min": [0.0, 0.0, 0.0], "max": [20.0, 30.0, 10.0]}}


def report_json(*checks: Mapping[str, object], parts: Sequence[Mapping[str, object]] | None = None, triangles: int = 12,
                unit: str = "mm") -> str:
    return json.dumps({"unit": unit, "parts": list(parts if parts is not None else [part_json()]), "triangles": triangles,
                       "checks": list(checks)})


def model_output(report: str | None, artifacts: Mapping[str, bytes] | None = None, exit_code: int = 0) -> Output:
    files = {REPORT_NAME: report} if report is not None else {}
    return Output("ran", exit_code, "", "", False, files, (), dict(artifacts if artifacts is not None else GOOD))


@dataclass
class World:
    url: str
    box: Box
    store: Site
    db: PoolDatabase
    workshop: Workshop
    runs: PostgresRuns
    rules: Rules
    alana: Owner
    zed: Owner

    async def bench(self, owner: Owner | None = None) -> int:
        return (await (self.workshop.open(owner or self.alana, "b"))).id

    async def add(self, bench: int, kind: str, body: str, owner: Owner | None = None) -> int:
        o = owner or self.alana
        applied = await self.workshop.apply(o, bench, Add(By(o.person_id), kind, Text("t", body), "small"))
        assert applied.piece_id is not None
        return applied.piece_id

    async def shelve(self, bench: int, piece: int) -> None:
        await self.workshop.apply(self.alana, bench, Archive(By(self.alana.person_id), piece))

    def chat_run(self, owner: Owner | None = None, language: Language = CAD) -> NewRun:
        o = owner or self.alana
        conv = int(_scalar(self.url, "INSERT INTO conversations (household_id, kind) VALUES (%s, 'chat') RETURNING id",
                           (o.household_id,)))
        turn = int(_scalar(self.url, "INSERT INTO turns (conversation_id, household_id, author, text) "
                           "VALUES (%s, %s, 'person', 'run it') RETURNING id", (conv, o.household_id)))
        return NewRun(o.household_id, conv, turn, "call-1", language, "box = 1", "", {})


def _scalar(url: str, query: str, params: tuple[object, ...] = ()) -> Any:
    from contract.conversations_support import scalar
    return scalar(url, query, params)


@asynccontextmanager
async def world(url: str, box: Box | None = None, store: Site | None = None) -> AsyncGenerator[World]:
    """Alana in household one, Zed in two; the real Workshop and Runs over Postgres; the fake Sandbox and store wired."""
    db = PoolDatabase(url)
    await db.open()
    rules = workshop_rules.load()
    h1, h2 = household(url, "one"), household(url, "two")
    made = World(url, box or Box(), store or Site(), db, PostgresWorkshop(db, rules), PostgresRuns(db), rules,
                 Owner(h1, person(url, h1, "Alana")), Owner(h2, person(url, h2, "Zed")))
    services.register(Database, db)
    services.register(Workshop, made.workshop)
    services.register(Runs, made.runs)
    services.register(Sandbox, made.box)
    services.register(ObjectStore, made.store)
    services.register(Live, Quiet())
    try:
        yield made
    finally:
        for interface in (Database, Workshop, Runs, Sandbox, ObjectStore, Live):
            services.unregister(interface)
        await db.close()


def run_cmd(owner: Owner, piece: int, version: int = 1, language: str = CAD) -> Run:
    return Run(By(owner.person_id), piece, version, language)


@dataclass
class Rig:
    client: TestClient
    homes: tuple[int, int]
    store: Site
    box: Box
    who: list[str] = field(default_factory=lambda: ["alana"])

    def as_(self, name: str) -> None:
        self.who[0] = name

    def command(self, bench: int, body: dict[str, Any]) -> dict[str, Any]:
        got = self.client.post(f"/api/benches/{bench}/commands", json=body)
        assert got.status_code == 200, got.text
        out: dict[str, Any] = got.json()
        return out

    def add(self, bench: int, kind: str, body: str) -> int:
        return int(self.command(bench, {"type": "add", "kind": kind, "title": "t", "body": body, "size": "small"})["piece_id"])

    def run_piece(self, bench: int, piece: int, version: int = 1, language: str = CAD) -> dict[str, Any]:
        got = self.client.post(f"/api/benches/{bench}/runs",
                               json={"piece_id": piece, "base_version": version, "run_language": language})
        assert got.status_code == 200, got.text
        out: dict[str, Any] = got.json()
        return out

    def bench(self, bench_id: int) -> dict[str, Any]:
        got = self.client.get(f"/api/benches/{bench_id}")
        assert got.status_code == 200, got.text
        out: dict[str, Any] = got.json()
        return out

    def new_bench(self) -> int:
        got = self.client.post("/api/benches", json={"title": "b"})
        assert got.status_code == 200, got.text
        return int(got.json()["id"])


@contextmanager
def rig(url: str, box: Box | None = None, link_key: str | None = LINK_KEY) -> Generator[Rig]:
    """The real app (a link key given or not), a signed-in person who can be switched, and the fake Sandbox and store
    registered after the app wired its own."""
    h1, h2 = household(url, "one"), household(url, "two")
    people = {"alana": Person(person(url, h1, "Alana"), h1, "Alana"), "zed": Person(person(url, h2, "Zed"), h2, "Zed")}
    files = {"files_endpoints": "http://nas.test:1", "files_bucket": "b", "files_access_key": "a", "files_secret_key": "s",
             "files_link_key": link_key} if link_key else {}
    settings = Settings(database_url=url, build_version="t", public_url=PUBLIC, **files)
    app = create_app(settings)
    play, store = box or Box(), Site()
    holder: dict[str, Rig] = {}

    def me() -> SignedIn:
        return SignedIn(1, people[holder["r"].who[0]])

    app.dependency_overrides[person_signed_in] = me
    with TestClient(app, base_url=PUBLIC, headers={"origin": PUBLIC}) as client:
        services.register(Sandbox, play)
        services.register(ObjectStore, store)
        services.register(Live, Quiet())
        holder["r"] = Rig(client, (h1, h2), store, play)
        yield holder["r"]
