"""The world for the bench-reaction tests: a real database, one person with a bench, a scripted model, and the
services the turn loop reaches. `quiet_for` makes a person's commands as old as the pause."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
import asyncio
from collections.abc import Mapping
from dataclasses import dataclass

from ashley import services
from ashley.channels.outbox import Outbox
from ashley.channels.postgres_outbox import PostgresOutbox
from ashley.conversations.conversations import Conversations
from ashley.conversations.inflight import InFlight
from ashley.conversations.postgres import PostgresConversations
from ashley.conversations.postgres_inflight import PostgresInFlight
from ashley.db.pool import PoolDatabase
from ashley.inference.inference import Inference
from ashley.inference.model import Message, Prompt, ToolSpec
from ashley.inference.reply import Reply
from ashley.initiative.initiative import Initiative, WorthSaying
from ashley.people.model import Account, Household, Person
from ashley.people.people import People
from ashley.senses.presence import Presence
from ashley.tools.tools import Tools
from ashley.workshop.commands import Add, Command, Cue, Edit
from ashley.workshop.model import HER, By, Owner, Text
from ashley.workshop.postgres import PostgresWorkshop
from ashley.workshop.rules import load as workshop_rules
from ashley.workshop.workshop import Workshop
from contract.conversations_support import POLICY, household, person, scalar
from wake_support import Model, Nobody, Switchboard

SECRET = "plans-for-the-shed"
SAYS = Reply(spoken="That draft reads well.", text="That draft reads well.", says="reply")
QUIETLY = Reply(spoken="Nothing to add.", text="Nothing to add.", says="none")


@dataclass
class OnePerson(People):
    home: Household

    async def household(self, household_id: int) -> Household | None:
        return self.home if household_id == self.home.id else None

    async def person_for(self, system: str, external_id: str) -> Person | None:
        return None

    async def accounts(self, household_id: int, system: str) -> tuple[Account, ...]:
        return ()


@dataclass
class World:
    url: str
    home: int
    elodie: int
    model: Model
    workshop: Workshop

    @property
    def owner(self) -> Owner:
        return Owner(self.home, self.elodie)

    async def bench(self) -> int:
        return (await self.workshop.open(self.owner, "essay")).id

    async def person_adds(self, bench: int, title: str = "Draft", kind: str = "document") -> int:
        done = await self.workshop.apply(self.owner, bench, Add(By(self.elodie), kind, Text(title, SECRET), "medium"))
        assert done.outcome == "accepted"
        return done.seq

    async def person_edits(self, bench: int, piece: int, version: int) -> None:
        command: Command = Edit(By(self.elodie), piece, version, Text("Draft", f"{SECRET} {version}"))
        assert (await self.workshop.apply(self.owner, bench, command)).outcome == "accepted"

    async def she_adds(self, bench: int) -> None:
        done = await self.workshop.apply(self.owner, bench, Add(HER, "note", Text("Note", "hers"), "small"))
        assert done.outcome == "accepted"

    async def video_cue(self, bench: int, by: By, piece: int) -> None:
        done = await self.workshop.apply(self.owner, bench, Cue(by, piece, "play", None))
        assert done.outcome == "accepted"

    def quiet_for(self, seconds: float) -> None:
        """Every command and reaction record so far is `seconds` older."""
        scalar(self.url, "WITH u AS (UPDATE bench_commands SET at = at - make_interval(secs => %s) RETURNING 1) "
                         "SELECT count(*) FROM u", (seconds,))
        scalar(self.url, "WITH u AS (UPDATE bench_reactions SET at = at - make_interval(secs => %s) RETURNING 1) "
                         "SELECT count(*) FROM u", (seconds,))

    def turns(self) -> list[tuple[str, str, str | None]]:
        got = scalar(self.url, "SELECT coalesce(json_agg(json_build_array(author, text, source) ORDER BY id), '[]') "
                               "FROM turns")
        return [(a, t, s) for a, t, s in got]

    async def until_hers(self, count: int, timeout: float = 5.0) -> None:
        """Waits until `count` turns of hers are stored, as a held reaction finishes in the background."""
        deadline = asyncio.get_running_loop().time() + timeout
        while sum(1 for a, _, _ in self.turns() if a == "ashley") < count:
            assert asyncio.get_running_loop().time() < deadline, "her turns never reached the count"
            await asyncio.sleep(0.02)

    def mark(self, bench: int) -> int:
        return int(scalar(self.url, "SELECT coalesce(max(to_seq), 0) FROM bench_reactions WHERE bench_id = %s",
                          (bench,)))


@asynccontextmanager
async def world(url: str) -> AsyncGenerator[World]:
    db = PoolDatabase(url, connect_timeout_s=5.0)
    await db.open()
    home = household(url)
    elodie = person(url, home, "Elodie")
    model, tools = Model(), Switchboard()
    w = World(url, home, elodie, model, PostgresWorkshop(db, workshop_rules()))
    services.register(People, OnePerson(Household(home, "home", "America/Denver", "", (Person(elodie, home, "Elodie"),))))
    services.register(Presence, Nobody())
    services.register(Conversations, PostgresConversations(db, POLICY))
    services.register(InFlight, PostgresInFlight(db, POLICY, 60.0))
    services.register(Outbox, PostgresOutbox(db, 600.0, POLICY))
    services.register(Tools, tools)
    services.register(Inference, model)
    services.register(Workshop, w.workshop)
    services.register(Initiative, WorthSaying())
    try:
        yield w
    finally:
        for interface in (People, Presence, Conversations, InFlight, Outbox, Tools, Inference, Workshop, Initiative):
            services.unregister(interface)
        await db.close()


def last_message(prompt: Prompt) -> str:
    return [m.text for m in prompt.messages if isinstance(m, Message)][-1]


def has_aside(tool: ToolSpec) -> bool:
    properties = tool.parameters.get("properties")
    return isinstance(properties, Mapping) and "aside" in properties
