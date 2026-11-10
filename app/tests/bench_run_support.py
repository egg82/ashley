"""A world for running a bench's code pieces over a real database: the Postgres Workshop and Runs on one pool, a
sandbox that plays the outputs it is given in turn and keeps every job, and a Live that keeps what it heard."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from ashley import services
from ashley.db.pool import PoolDatabase
from ashley.live.events import Event, Watcher
from ashley.live.fanout import Subscription
from ashley.live.live import Live
from ashley.runs.model import Job, Language, Output
from ashley.runs.postgres import PostgresRuns
from ashley.runs.runs import Runs
from ashley.runs.sandbox import Sandbox, SandboxUnavailable
from ashley.workshop import rules as workshop_rules
from ashley.workshop.commands import Add
from ashley.workshop.model import By, Owner, Text
from ashley.workshop.postgres import PostgresWorkshop
from ashley.workshop.workshop import Workshop

RULES = workshop_rules.load()
OK = Output("ran", 0, "3\n", "", False, {"state.txt": "1"}, ())


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

    outputs: list[Output] = field(default_factory=lambda: [OK])
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


@dataclass
class World:
    box: Box
    heard: Heard
    database: PoolDatabase


@asynccontextmanager
async def world(url: str, box: Box | None = None) -> AsyncGenerator[World]:
    database = PoolDatabase(url)
    await database.open()
    made = World(box or Box(), Heard(), database)
    services.register(Workshop, PostgresWorkshop(database, RULES))
    services.register(Runs, PostgresRuns(database))
    services.register(Sandbox, made.box)
    services.register(Live, made.heard)
    try:
        yield made
    finally:
        for interface in (Workshop, Runs, Sandbox, Live):
            services.unregister(interface)
        await database.close()


def code(owner: Owner | None, body: str = "print(1+2)") -> Add:
    return Add(By(None if owner is None else owner.person_id), "code", Text("sum", body), "medium")


def note(owner: Owner) -> Add:
    return Add(By(owner.person_id), "note", Text("n", "x"), "medium")
