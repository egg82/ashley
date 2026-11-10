"""Support for the blind bench-run tests: rules with a code kind, command builders, a fake Sandbox that plays outputs
and keeps its jobs, and a world of the real Workshop and Runs over one Postgres pool."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from types import MappingProxyType

from ashley import services
from ashley.db.pool import PoolDatabase
from ashley.live.events import Event, Watcher
from ashley.live.fanout import Subscription
from ashley.live.live import Live
from ashley.runs.model import Job, Language, Outcome, Output
from ashley.runs.postgres import PostgresRuns
from ashley.runs.runs import Runs
from ashley.runs.sandbox import Sandbox, SandboxUnavailable
from ashley.workshop.commands import Add, Command, Run
from ashley.workshop.decide import EMPTY, Accepted, BenchState, Decision, Refused, decide
from ashley.workshop.model import By, Owner, Text
from ashley.workshop.postgres import PostgresWorkshop
from ashley.workshop.rules import Kind, Rules
from ashley.workshop.workshop import Workshop
from contract.conversations_support import household, person

NOTE = Kind("note", "stored", "Note", 100, "plain")
CODE = Kind("code", "stored", "Code", 100, "code", "python")
RULES = Rules(MappingProxyType({"note": NOTE, "code": CODE}), max_pieces=5, title_max_chars=10, recent_commands=20, undo_window=100)
NO_CODE = Rules(MappingProxyType({"note": NOTE}), max_pieces=5, title_max_chars=10, recent_commands=20, undo_window=100)
ALANA = By(7)
HER = By(None)

RAN = Output("ran", 0, "OUT-A", "ERR-A", False, {"state.txt": "S1"}, ())


def add_code(body: str = "print(1)", by: By = ALANA) -> Add:
    return Add(by, "code", Text("c", body), "small")


def add_note(by: By = ALANA) -> Add:
    return Add(by, "note", Text("n", "x"), "small")


def run_cmd(piece_id: int, base_version: int = 1, language: str = "python", by: By = ALANA) -> Run:
    return Run(by, piece_id, base_version, language)


def fold(*commands: Command) -> list[Decision]:
    out: list[Decision] = []
    state: BenchState = EMPTY
    for command in commands:
        decision = decide(state, command, RULES)
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
    def __init__(self) -> None:
        self.events: list[Event] = []

    def publish(self, event: Event) -> None:
        self.events.append(event)

    def subscribe(self, viewer: Watcher) -> Subscription:
        raise NotImplementedError


@dataclass
class Box(Sandbox):
    """Plays `outputs` in turn (the last repeats); `down` makes it unable to run anything."""

    outputs: list[Output] = field(default_factory=lambda: [RAN])
    jobs: list[Job] = field(default_factory=list[Job])
    down: bool = False
    offered: tuple[Language, ...] = ("python",)

    def languages(self) -> tuple[Language, ...]:
        return self.offered

    async def run(self, job: Job) -> Output:
        self.jobs.append(job)
        if self.down:
            raise SandboxUnavailable("down")
        return self.outputs[min(len(self.jobs) - 1, len(self.outputs) - 1)]


def out(outcome: Outcome, files: dict[str, str] | None = None, stdout: str = "") -> Output:
    exit_code = 0 if outcome == "ran" else None
    return Output(outcome, exit_code, stdout, "", False, files or {}, ())


@dataclass
class World:
    box: Box
    heard: Heard
    database: PoolDatabase
    workshop: Workshop
    runs: Runs
    alana: Owner
    sam: Owner
    zed: Owner


@asynccontextmanager
async def world(url: str, box: Box | None = None) -> AsyncGenerator[World]:
    """Alana and Sam in one household, Zed in another; Workshop, Runs, Sandbox and Live wired."""
    database = PoolDatabase(url)
    await database.open()
    h1, h2 = household(url, "one"), household(url, "two")
    alana = Owner(h1, person(url, h1, "Alana"))
    sam = Owner(h1, person(url, h1, "Sam"))
    zed = Owner(h2, person(url, h2, "Zed"))
    made = World(box or Box(), Heard(), database, PostgresWorkshop(database, RULES), PostgresRuns(database),
                 alana, sam, zed)
    services.register(Workshop, made.workshop)
    services.register(Runs, made.runs)
    services.register(Sandbox, made.box)
    services.register(Live, made.heard)
    try:
        yield made
    finally:
        for interface in (Workshop, Runs, Sandbox, Live):
            services.unregister(interface)
        await database.close()


def by(owner: Owner) -> By:
    return By(owner.person_id)
