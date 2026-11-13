"""Shared pieces of the bench-reaction blind contract tests: a real database with households that each own a bench
person, a scripted model and the services the turn loop reaches, helpers that age a bench's commands and reactions,
and a sentinel planted in piece text so any leak of a piece's words is found."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

import pytest
from ashley import logs, services
from ashley.channels.outbox import Outbox
from ashley.channels.postgres_outbox import PostgresOutbox
from ashley.channels.wake.bench_react_config import CONFIG
from ashley.channels.wake.bench_reacts import BenchReacts
from ashley.conversations.conversations import Conversations
from ashley.conversations.inflight import InFlight
from ashley.conversations.postgres import PostgresConversations
from ashley.conversations.postgres_inflight import PostgresInFlight
from ashley.db.pool import PoolDatabase
from ashley.inference.inference import Inference
from ashley.inference.model import Message, Prompt
from ashley.inference.reply import Reply
from ashley.initiative.initiative import Initiative
from initiative_support import speaking
from ashley.people.model import Account, Household, Person
from ashley.people.people import People
from ashley.senses.presence import Presence
from ashley.tools.tools import Tools
from ashley.workshop.commands import Add, Command, Edit
from ashley.workshop.model import HER, By, Owner, Text
from ashley.workshop.postgres import PostgresWorkshop
from ashley.workshop.rules import load as workshop_rules
from ashley.workshop.workshop import Workshop
from contract.conversations_support import events, household, person, POLICY, scalar
from wake_support import Model, Nobody, Switchboard

SENTINEL = "zebra-quartz-7731"
SAYS = Reply(spoken="That draft reads well.", text="That draft reads well.", says="reply")
QUIETLY = Reply(spoken="Nothing to add.", text="Nothing to add.", says="none")
PAUSE = CONFIG.pause_s
OLD = PAUSE * 10


@dataclass
class Home:
    id: int
    person: int

    @property
    def owner(self) -> Owner:
        return Owner(self.id, self.person)


@dataclass
class Households(People):
    homes: dict[int, Household]

    async def household(self, household_id: int) -> Household | None:
        return self.homes.get(household_id)

    async def person_for(self, system: str, external_id: str) -> Person | None:
        return None

    async def accounts(self, household_id: int, system: str) -> tuple[Account, ...]:
        return ()


@dataclass
class World:
    url: str
    model: Model
    workshop: Workshop
    homes: list[Home] = field(default_factory=list[Home])

    @property
    def home(self) -> Home:
        return self.homes[0]

    async def bench(self, home: Home | None = None, title: str = "essay") -> int:
        return (await self.workshop.open((home or self.home).owner, title)).id

    async def person_adds(self, bench: int, title: str = "Draft", kind: str = "document",
                          home: Home | None = None) -> int:
        h = home or self.home
        done = await self.workshop.apply(h.owner, bench, Add(By(h.person), kind, Text(title, SENTINEL), "medium"))
        assert done.outcome == "accepted"
        return done.seq

    async def person_edits(self, bench: int, piece: int, version: int, home: Home | None = None) -> int:
        h = home or self.home
        command: Command = Edit(By(h.person), piece, version, Text("Draft", f"{SENTINEL} {version}"))
        done = await self.workshop.apply(h.owner, bench, command)
        assert done.outcome == "accepted"
        return done.seq

    async def she_adds(self, bench: int, home: Home | None = None) -> int:
        done = await self.workshop.apply((home or self.home).owner, bench, Add(HER, "note", Text("Note", "hers"), "small"))
        assert done.outcome == "accepted"
        return done.seq

    def age_commands(self, bench: int, seconds: float, up_to: int | None = None) -> None:
        scalar(self.url, "WITH u AS (UPDATE bench_commands SET at = clock_timestamp() - make_interval(secs => %s) "
                         "WHERE bench_id = %s AND seq <= %s RETURNING 1) SELECT count(*) FROM u",
               (seconds, bench, up_to if up_to is not None else 1 << 30))

    def age_reaction(self, bench: int, to_seq: int, seconds: float) -> None:
        got = scalar(self.url, "WITH u AS (UPDATE bench_reactions SET at = clock_timestamp() - make_interval(secs => %s) "
                               "WHERE bench_id = %s AND to_seq = %s RETURNING 1) SELECT count(*) FROM u",
                     (seconds, bench, to_seq))
        assert got == 1

    def quiet(self, seconds: float) -> None:
        """Every command so far is `seconds` old; the reaction records are left as they are."""
        scalar(self.url, "WITH u AS (UPDATE bench_commands SET at = clock_timestamp() - make_interval(secs => %s) "
                         "RETURNING 1) SELECT count(*) FROM u", (seconds,))

    def reaction_rows(self, bench: int) -> list[int]:
        got = scalar(self.url, "SELECT coalesce(json_agg(to_seq ORDER BY to_seq), '[]') FROM bench_reactions "
                               "WHERE bench_id = %s", (bench,))
        return [int(x) for x in got]

    def mark(self, bench: int) -> int:
        return int(scalar(self.url, "SELECT coalesce(max(to_seq), 0) FROM bench_reactions WHERE bench_id = %s", (bench,)))

    def turns(self) -> list[tuple[str, str, str | None]]:
        got = scalar(self.url, "SELECT coalesce(json_agg(json_build_array(author, text, source) ORDER BY id), '[]') "
                               "FROM turns")
        return [(a, t, s) for a, t, s in got]

    def everything_stored(self) -> str:
        """The text of every turn and its source, joined: where a leaked piece word would be found."""
        return "\n".join(f"{a} {t} {s}" for a, t, s in self.turns())


@asynccontextmanager
async def world(url: str, households: int = 1) -> AsyncGenerator[World]:
    db = PoolDatabase(url, connect_timeout_s=5.0)
    await db.open()
    model, tools = Model(), Switchboard()
    w = World(url, model, PostgresWorkshop(db, workshop_rules()))
    homes: dict[int, Household] = {}
    for n in range(households):
        hid = household(url, f"home{n}")
        pid = person(url, hid, f"Person{n}")
        w.homes.append(Home(hid, pid))
        homes[hid] = Household(hid, f"home{n}", "America/Denver", "", (Person(pid, hid, f"Person{n}"),))
    services.register(People, Households(homes))
    services.register(Presence, Nobody())
    services.register(Conversations, PostgresConversations(db, POLICY))
    services.register(InFlight, PostgresInFlight(db, POLICY, 60.0))
    services.register(Outbox, PostgresOutbox(db, 600.0, POLICY))
    services.register(Tools, tools)
    services.register(Inference, model)
    services.register(Workshop, w.workshop)
    services.register(Initiative, speaking())
    try:
        yield w
    finally:
        for interface in (People, Presence, Conversations, InFlight, Outbox, Tools, Inference, Workshop, Initiative):
            services.unregister(interface)
        await db.close()


def last_message(prompt: Prompt) -> str:
    return [m.text for m in prompt.messages if isinstance(m, Message)][-1]


def logged(capsys: pytest.CaptureFixture[str], event: str) -> tuple[list[dict[str, str]], str]:
    """The logfmt lines of `event` so far and everything printed, for a leak check."""
    seen = capsys.readouterr()
    text = seen.out + seen.err
    return events(text, event), text


def start_logs() -> None:
    logs.setup()


async def react(w: World, reacts: BenchReacts, bench: int, piece: int, version: int, reply: Reply = SAYS) -> int:
    """The person edits, goes quiet for longer than the pause, and one sweep runs; returns the edit's seq."""
    seq = await w.person_edits(bench, piece, version)
    w.quiet(OLD)
    w.model.script = [reply]
    assert await reacts.sweep() == 1
    return seq
