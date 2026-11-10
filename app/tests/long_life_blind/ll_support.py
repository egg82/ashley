"""Support for the long-life blind tests: rules with a chosen undo window, command builders, a fold of `decide`, and a
world of the real Workshop and Runs over one Postgres pool."""

from collections.abc import AsyncGenerator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from types import MappingProxyType

from ashley import services
from ashley.db.pool import PoolDatabase
from ashley.live.events import Event, Watcher
from ashley.live.fanout import Subscription
from ashley.live.live import Live
from ashley.runs.model import BenchRun, Job, Language, NewRun, Outcome, Output
from ashley.runs.postgres import PostgresRuns
from ashley.runs.runs import Runs
from ashley.runs.sandbox import Sandbox
from ashley.workshop.commands import Add, Command, Remove, Run, Undo
from ashley.workshop.decide import EMPTY, Accepted, BenchState, Decision, Refused, decide
from ashley.workshop.model import By, Owner, Text
from ashley.workshop.postgres import PostgresWorkshop
from ashley.workshop.rules import Kind, Rules
from ashley.workshop.workshop import Workshop
from contract.conversations_support import household, person

NOTE = Kind("note", "stored", "Note", 100, "plain")
CODE = Kind("code", "stored", "Code", 100, "code", "python")
ALANA = By(7)
HER = By(None)


def rules(window: int) -> Rules:
    return Rules(MappingProxyType({"note": NOTE, "code": CODE}), max_pieces=50, title_max_chars=10, recent_commands=20,
                 undo_window=window)


def add(kind: str = "note", by: By = ALANA) -> Add:
    return Add(by, kind, Text("t", "print(1)" if kind == "code" else "x"), "small")


def bad(by: By = ALANA) -> Remove:
    """A command every bench refuses: no such piece."""
    return Remove(by, 999)


def undo(seq: int, by: By = ALANA) -> Undo:
    return Undo(by, seq)


def run_cmd(piece_id: int, by: By = ALANA) -> Run:
    return Run(by, piece_id, 1, "python")


def fold(commands: Sequence[Command], window: int) -> list[Decision]:
    out: list[Decision] = []
    state: BenchState = EMPTY
    for command in commands:
        decision = decide(state, command, rules(window))
        out.append(decision)
        state = decision.state
    return out


def accepted(decision: Decision) -> Accepted:
    assert isinstance(decision, Accepted), f"expected an acceptance, got {decision}"
    return decision


def reason(decision: Decision) -> str:
    assert isinstance(decision, Refused), f"expected a refusal, got {decision}"
    return decision.reason


class Heard(Live):
    def publish(self, event: Event) -> None:
        pass

    def subscribe(self, viewer: Watcher) -> Subscription:
        raise NotImplementedError


class Box(Sandbox):
    def languages(self) -> tuple[Language, ...]:
        return ("python",)

    async def run(self, job: Job) -> Output:
        return RAN


RAN = Output("ran", 0, "", "", False, {}, ())


def out(outcome: Outcome, files: dict[str, str] | None = None) -> Output:
    return Output(outcome, 0 if outcome == "ran" else None, "", "", False, files or {}, ())


@dataclass
class World:
    database: PoolDatabase
    workshop: Workshop
    runs: Runs
    alana: Owner
    zed: Owner
    url: str
    benches: list[int] = field(default_factory=list[int])


@asynccontextmanager
async def world(url: str, window: int = 100) -> AsyncGenerator[World]:
    """Alana in one household, Zed in another; Workshop (with `window`), Runs, Sandbox and Live wired."""
    database = PoolDatabase(url)
    await database.open()
    h1, h2 = household(url, "one"), household(url, "two")
    alana = Owner(h1, person(url, h1, "Alana"))
    zed = Owner(h2, person(url, h2, "Zed"))
    made = World(database, PostgresWorkshop(database, rules(window)), PostgresRuns(database), alana, zed, url)
    services.register(Workshop, made.workshop)
    services.register(Runs, made.runs)
    services.register(Sandbox, Box())
    services.register(Live, Heard())
    try:
        yield made
    finally:
        for interface in (Workshop, Runs, Sandbox, Live):
            services.unregister(interface)
        await database.close()


async def bench_with_codes(w: World, owner: Owner | None = None, pieces: int = 2) -> int:
    """A bench of `pieces` code pieces (ids 1..pieces), opened by `owner`."""
    owner = owner or w.alana
    bench = await w.workshop.open(owner, "b")
    for _ in range(pieces):
        applied = await w.workshop.apply(owner, bench.id, add("code", HER))
        assert applied.outcome == "accepted"
    return bench.id


async def start(w: World, bench_id: int, piece: int = 1, owner: Owner | None = None) -> int:
    """A run of `piece` made by a logged Run command, started and not finished."""
    owner = owner or w.alana
    applied = await w.workshop.apply(owner, bench_id, run_cmd(piece, HER))
    assert applied.outcome == "accepted"
    return await w.runs.start(NewRun(owner.household_id, None, None, None, "python", "s", "", {},
                                     BenchRun(bench_id, applied.seq, piece, 1)))


async def done(w: World, bench_id: int, piece: int = 1, output: Output = RAN, owner: Owner | None = None) -> int:
    run_id = await start(w, bench_id, piece, owner)
    await w.runs.finish(run_id, output)
    return run_id


async def alive(w: World, ids: Sequence[int], owner: Owner | None = None) -> list[int]:
    household_id = (owner or w.alana).household_id
    return [i for i in ids if await w.runs.get(household_id, i) is not None]
