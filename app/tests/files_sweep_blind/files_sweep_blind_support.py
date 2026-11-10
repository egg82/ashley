"""Shared pieces of the files-sweep blind contract tests: an object store written against the `ObjectStore` interface
alone (it stamps each write with a test clock, can be taken down, and can refuse listing or deleting), the real
Workshop and Postgres candidates on a throwaway database, and one rig that runs sweep passes at a chosen time."""

import asyncio
import hashlib
from collections.abc import AsyncGenerator, Coroutine, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any, TypeVar

import pytest
from ashley import services
from ashley.db.database import Database
from ashley.db.pool import PoolDatabase
from ashley.files import config as files_config
from ashley.files import sweep
from ashley.files.config import FilesConfig
from ashley.files.intake import key_of
from ashley.files.mirror import MirroredStore
from ashley.files.orphans import PostgresCandidates
from ashley.files.store import ObjectStore, StoreUnavailable
from ashley.live.live import Live
from ashley.workshop import rules as workshop_rules
from ashley.workshop.bench_file import add_file
from ashley.workshop.commands import Add, Archive, Remove, Restore, Undo
from ashley.workshop.model import By, Owner, Text
from ashley.workshop.postgres import PostgresWorkshop
from ashley.workshop.rules import Rules
from ashley.workshop.workshop import Workshop
from contract.conversations_support import household, person
from live_support import FakeLive

T = TypeVar("T")

START = datetime(2030, 1, 1, 12, 0, tzinfo=UTC)
CONFIG: FilesConfig = files_config.load()
GRACE = timedelta(seconds=CONFIG.sweep_grace_s)
PNG = bytes.fromhex("89504e470d0a1a0a") + b"\x00\x00\x00\rIHDRrest"
PDF = b"%PDF-1.7\n1 0 obj\n"
UNDO_WINDOW = 3


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


class Clock:
    """The time the sweep and the stores both read."""

    def __init__(self) -> None:
        self.now = START

    def __call__(self) -> datetime:
        return self.now

    def advance(self, by: timedelta) -> None:
        self.now += by


class Site(ObjectStore):
    """One site's store. A write is stamped with the clock (or with `at`); `down` fails every call, `no_listing` and
    `no_delete` fail that call kind only. `calls` records (verb, argument) in order."""

    def __init__(self, clock: Clock, name: str = "a") -> None:
        self.clock = clock
        self.name = name
        self.held: dict[str, bytes] = {}
        self.written: dict[str, datetime] = {}
        self.down = False
        self.no_listing = False
        self.no_delete = False
        self.bad_delete: set[str] = set()
        self.calls: list[tuple[str, str]] = []

    def _reach(self, verb: str, arg: str) -> None:
        self.calls.append((verb, arg))
        if self.down or (verb == "listing" and self.no_listing) or (verb == "delete" and (self.no_delete or arg in self.bad_delete)):
            raise StoreUnavailable(f"{self.name} unreachable")

    def keep(self, key: str, data: bytes = b"x", age: timedelta = timedelta(0)) -> None:
        """Hold `key` as if written `age` before now, without a call."""
        self.held[key] = data
        self.written[key] = self.clock() - age

    def of(self, verb: str) -> list[str]:
        return [a for v, a in self.calls if v == verb]

    async def put(self, key: str, data: bytes) -> int:
        self._reach("put", key)
        self.held[key] = data
        self.written[key] = self.clock()
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


def key(n: int, h: int = 1) -> str:
    """A key under the files' prefix that no piece names (its hash is made up)."""
    return key_of(h, f"{n:064x}")


OLD = GRACE + timedelta(seconds=1)


@dataclass
class Rig:
    url: str
    clock: Clock
    sites: list[Site]
    mirror: MirroredStore
    workshop: Workshop
    rules: Rules
    config: FilesConfig
    candidates: PostgresCandidates
    alana: Owner
    zed: Owner
    live: FakeLive = field(default_factory=FakeLive)

    async def named(self) -> frozenset[str]:
        from ashley.workshop.file_references import named_keys
        return await named_keys(self.rules)

    async def pass_(self) -> sweep.Swept | None:
        return await sweep.run_once(self.mirror, self.named, self.candidates, self.config, self.clock)

    async def passes(self, n: int) -> None:
        for _ in range(n):
            await self.pass_()

    async def bench(self, owner: Owner | None = None) -> int:
        return (await self.workshop.open(owner or self.alana, "b")).id

    async def file(self, bench: int, data: bytes = PNG, owner: Owner | None = None, name: str = "p.png") -> tuple[str, int]:
        """Add `data` to a bench through the real intake; the key its bytes are under and the piece's id."""
        o = owner or self.alana
        stored, applied = await add_file(o, bench, By(o.person_id), data, name, "", self.rules)
        assert applied.piece_id is not None
        return key_of(o.household_id, stored.sha256), applied.piece_id

    async def note(self, bench: int, owner: Owner | None = None) -> None:
        o = owner or self.alana
        await self.workshop.apply(o, bench, Add(By(o.person_id), "note", Text("n", "x"), "small"))

    async def remove(self, bench: int, piece: int) -> None:
        await self.workshop.apply(self.alana, bench, Remove(By(self.alana.person_id), piece))

    async def shelve(self, bench: int, piece: int) -> None:
        await self.workshop.apply(self.alana, bench, Archive(By(self.alana.person_id), piece))

    async def unshelve(self, bench: int, piece: int) -> None:
        await self.workshop.apply(self.alana, bench, Restore(By(self.alana.person_id), piece))

    async def undo(self, bench: int, seq: int) -> None:
        await self.workshop.apply(self.alana, bench, Undo(By(self.alana.person_id), seq))

    def age_everything(self, by: timedelta) -> None:
        """Make every held key older by `by`, on every site."""
        for s in self.sites:
            for k in s.written:
                s.written[k] -= by

    def holders(self, k: str) -> list[bool]:
        return [k in s.held for s in self.sites]


@asynccontextmanager
async def rig(url: str, sites: int = 2, max_pieces: int | None = None) -> AsyncGenerator[Rig]:
    """The real Postgres Workshop and candidates, over `sites` fake stores, with the undo window cut to `UNDO_WINDOW`."""
    db = PoolDatabase(url)
    await db.open()
    clock = Clock()
    stores = [Site(clock, chr(ord("a") + i)) for i in range(sites)]
    mirror = MirroredStore(list(stores))
    rules = replace(workshop_rules.load(), undo_window=UNDO_WINDOW)
    if max_pieces is not None:
        rules = replace(rules, max_pieces=max_pieces)
    workshop = PostgresWorkshop(db, rules)
    h1, h2 = household(url, "one"), household(url, "two")
    live = FakeLive()
    services.register(Database, db)
    services.register(Live, live)
    services.register(Workshop, workshop)
    services.register(ObjectStore, mirror)
    try:
        yield Rig(url, clock, stores, mirror, workshop, rules, CONFIG, PostgresCandidates(),
                  Owner(h1, person(url, h1, "Alana")), Owner(h2, person(url, h2, "Zed")), live)
    finally:
        for interface in (Database, Live, Workshop, ObjectStore):
            services.unregister(interface)
        await db.close()

