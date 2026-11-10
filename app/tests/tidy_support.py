"""Fixtures for the tidy pass's tests: two invented notes of a birdhouse bench as the database held them, a
scripted `Inference` that answers the `bench_tidy` task, and a real Workshop and Tidy over a migrated database."""

import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from ashley import services
from ashley.db.pool import PoolDatabase
from ashley.inference.inference import Inference, InferenceRejected, InferenceUnavailable, NullInference
from ashley.inference.model import Prompt, Task
from ashley.live.live import Live
from ashley.tidy.pointer import Found, Pointed
from ashley.tidy.postgres import PostgresTidy
from ashley.tidy.tidy import Finding, NewFinding, Tidy, TidyUnavailable
from ashley.workshop import rules as workshop_rules
from ashley.workshop.commands import Add
from ashley.workshop.model import By, Owner, Text
from ashley.workshop.postgres import PostgresWorkshop
from ashley.workshop.workshop import Workshop
from contract.conversations_support import household, person
from live_support import FakeLive

T = TypeVar("T", bound=BaseModel)
CAPTURED = Path(__file__).parent / "bench_tidy_captured"
HEADER = "The questions it answered: To confirm for the roof pitch (rafter cut, ridge height):"
STALE = "Still no repo link found (re-checked Tuesday evening, including the maker's video description, which look-up couldn't read)."
CRACKER = "The maker's own cut list (still not found)."


def captured(name: str) -> Text:
    """A note as the database held it: its title, then `---`, then its body."""
    title, body = (CAPTURED / name).read_text().split("\n---\n", 1)
    return Text(title, body.rstrip("\n"))


CODE_STATUS = captured("status_note.txt")
DECOMPILE = captured("check_note.txt")


@dataclass
class ScriptedInference(NullInference):
    """Answers every `bench_tidy` call with `reply`, or raises InferenceUnavailable while `down` and InferenceRejected while `rejected`; keeps the prompts."""

    reply: Pointed = field(default_factory=lambda: Pointed(findings=[]))
    down: bool = False
    rejected: bool = False
    asked: list[tuple[Task, Prompt]] = field(default_factory=list[tuple[Task, Prompt]])

    async def generate(self, task: Task, prompt: Prompt, output: type[T], *, conversation_id: int | None = None) -> T:
        self.asked.append((task, prompt))
        if self.down:
            raise InferenceUnavailable("down")
        if self.rejected:
            raise InferenceRejected("every route rejected the request")
        assert output is Pointed
        return output.model_validate(self.reply.model_dump())


def found(piece_id: int, kind: str, quote: str, by: int | None = None, why: str = "because") -> Found:
    return Found.model_validate({"piece_id": piece_id, "kind": kind, "quote": quote, "by_piece_id": by, "why": why})


@dataclass
class Bench:
    owner: Owner
    id: int
    tidy: Tidy
    inference: ScriptedInference


@asynccontextmanager
async def benches(url: str, household_id: int, person_id: int) -> AsyncGenerator[Bench]:
    """A bench of the person's on the real Workshop and Tidy, with a scripted Inference registered."""
    database = PoolDatabase(url)
    await database.open()
    inference = ScriptedInference()
    tidy = PostgresTidy(database)
    services.register(Live, FakeLive())
    services.register(Workshop, PostgresWorkshop(database, workshop_rules.load()))
    services.register(Tidy, tidy)
    services.register(Inference, inference)
    try:
        owner = Owner(household_id, person_id)
        yield Bench(owner, (await services.get(Workshop).open(owner, "loaf")).id, tidy, inference)
    finally:
        await database.close()


async def add(bench: Bench, kind: str, text: Text) -> int:
    """The id of a piece the person added."""
    applied = await services.get(Workshop).apply(bench.owner, bench.id, Add(By(bench.owner.person_id), kind, text, "medium"))
    assert applied.outcome == "accepted" and applied.piece_id is not None
    return applied.piece_id


Scenario = Callable[[Bench], Awaitable[None]]


def scenario(url: str, body: Scenario) -> None:
    home = household(url)
    owner = person(url, home)

    async def go() -> None:
        async with benches(url, home, owner) as bench:
            await body(bench)

    asyncio.run(asyncio.wait_for(go(), 25))


async def two_notes(bench: Bench) -> tuple[int, int]:
    """The bench's notes from bench 6, and the model scripted to point at four passages, one of them invented."""
    status, decompile = await add(bench, "note", CODE_STATUS), await add(bench, "note", DECOMPILE)
    bench.inference.reply.findings.extend([
        found(status, "debris", HEADER, why="the header appears twice"),
        found(status, "superseded", STALE, decompile, "the session found it"),
        found(decompile, "contradicts", CRACKER, status),
        found(status, "debris", "a line the model made up from nothing")])
    return status, decompile




@dataclass
class RecordingTidy(Tidy):
    """Keeps the benches `checked` was asked about, then reports itself unreachable so the pass goes no further."""

    asked: list[int] = field(default_factory=list[int])

    async def checked(self, bench_id: int) -> dict[int, int]:
        self.asked.append(bench_id)
        raise TidyUnavailable("recording only")

    async def begin(self, household_id: int, bench_id: int, lock_s: int) -> bool:
        raise NotImplementedError

    async def finish(self, household_id: int, bench_id: int, versions: dict[int, int], found: tuple[NewFinding, ...],
                     keep_s: int) -> None:
        raise NotImplementedError

    async def release(self, bench_id: int) -> None:
        raise NotImplementedError

    async def findings(self, bench_id: int) -> tuple[Finding, ...]:
        raise NotImplementedError

    async def dismiss(self, bench_id: int, finding_id: int) -> bool:
        raise NotImplementedError

    async def clear(self, bench_id: int, finding_ids: tuple[int, ...]) -> None:
        raise NotImplementedError
