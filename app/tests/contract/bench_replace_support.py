"""Helpers for the blind bench_replace contract tests: a real Postgres Workshop with small limits (a 20-character
window, a 40-character note), her bench tools called through `call`, and the bench read back through the Workshop."""

import json
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from ashley import services
from ashley.db.pool import PoolDatabase
from ashley.inference.model import ToolCall
from ashley.live.live import Live
from ashley.tools.bench_config import BenchToolsConfig
from ashley.tools.bench_tools import BenchTools
from ashley.workshop.commands import Add
from ashley.workshop.model import By, Owner, Piece, Text
from ashley.workshop.postgres import PostgresWorkshop
from ashley.workshop.rules import Kind, Rules
from ashley.workshop.workshop import Workshop
from contract.conversations_support import household, person, run
from live_support import FakeLive

WINDOW = 20
NOTE_MAX = 40
RULES = Rules(MappingProxyType({
    "note": Kind("note", "stored", "Note", NOTE_MAX, "plain"),
    "doc": Kind("doc", "stored", "Doc", 1000, "markdown"),
    "code": Kind("code", "stored", "Code", 1000, "code", "text"),
}), max_pieces=5, title_max_chars=20, recent_commands=10, undo_window=100)
CONFIG = BenchToolsConfig(read_body_chars=50, piece_chars=WINDOW, recent_commands=5, lead_adds=2)


@dataclass(frozen=True)
class Result:
    is_error: bool
    data: dict[str, Any]
    raw: str


def _object(text: str) -> dict[str, Any]:
    """The JSON object `text` holds, empty when it is not one (an error line)."""
    try:
        loose: Any = json.loads(text)
        return dict[str, Any](loose)
    except (ValueError, TypeError):
        return {}


class Session:
    """One bench on a real Workshop and her tools on it. `tools` is one turn's instance (what she has read lives in
    it); `new_turn` makes another with nothing read."""

    def __init__(self, workshop: Workshop, owner: Owner, bench_id: int) -> None:
        self.workshop = workshop
        self.owner = owner
        self.bench_id = bench_id
        self.tools = self._tools()
        self._n = 0

    def _tools(self) -> BenchTools:
        return BenchTools(self.owner.household_id, self.owner.person_id, self.bench_id, RULES, CONFIG)

    def new_turn(self) -> None:
        self.tools = self._tools()

    async def call(self, name: str, **arguments: object) -> Result:
        self._n += 1
        out = await self.tools.call(ToolCall(f"c{self._n}", name, arguments))
        data = _object(out.content)
        return Result(out.is_error, data, out.content)

    async def person_adds(self, kind: str, body: str, title: str = "t") -> int:
        """A piece added by the person, so she has not read it."""
        applied = await self.workshop.apply(self.owner, self.bench_id,
                                            Add(By(self.owner.person_id), kind, Text(title, body), "small"))
        assert applied.outcome == "accepted" and applied.piece_id is not None
        return applied.piece_id

    async def piece(self, piece_id: int) -> Piece:
        view = await self.workshop.read(self.owner, self.bench_id)
        return next(p for p in view.pieces if p.id == piece_id)

    async def body(self, piece_id: int) -> str:
        return (await self.piece(piece_id)).text.body

    async def version(self, piece_id: int) -> int:
        return (await self.piece(piece_id)).version

    async def log_len(self) -> int:
        return len(await self.workshop.log(self.owner, self.bench_id))


@asynccontextmanager
async def session(url: str) -> AsyncGenerator[Session]:
    h = household(url, "one")
    owner = Owner(h, person(url, h, "Alana"))
    db = PoolDatabase(url)
    await db.open()
    services.register(Live, FakeLive())
    try:
        workshop = PostgresWorkshop(db, RULES)
        services.register(Workshop, workshop)
        bench = await workshop.open(owner, "B")
        yield Session(workshop, owner, bench.id)
    finally:
        await db.close()


PLAIN = "0123456789ABCDEFGHIJ" "klmnopqrstuvwxyz!?" "0123456789"  # 48 characters, every run of 3 distinct


def scenario(db_url: str, body: Callable[[Session], Awaitable[None]]) -> None:
    async def go() -> None:
        async with session(db_url) as s:
            await body(s)

    run(go())


async def windows(s: Session, pid: int) -> list[dict[str, Any]]:
    """Every window of a piece read from offset 0, each at the offset the one before ended."""
    out: list[dict[str, Any]] = []
    offset = 0
    while True:
        r = await s.call("bench_read_piece", piece_id=pid, offset=offset)
        assert not r.is_error, r.raw
        out.append(r.data)
        if not r.data["body_cut"]:
            return out
        offset += len(r.data["body"])
        assert len(out) < 100
