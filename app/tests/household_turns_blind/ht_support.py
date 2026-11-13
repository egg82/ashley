"""Pieces of the household-turn blind tests: a household named Willow with Alana and Sam, hand-built turns, and a
wake world over real Postgres with a scripted model."""

import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from ashley import services
from ashley.channels.outbox import Outbox
from ashley.channels.postgres_outbox import PostgresOutbox
from ashley.conversations.conversations import Conversations
from ashley.conversations.inflight import InFlight
from ashley.conversations.model import Author, Turn
from ashley.conversations.postgres import PostgresConversations
from ashley.conversations.postgres_inflight import PostgresInFlight
from ashley.db.pool import PoolDatabase
from ashley.inference.inference import Inference
from ashley.inference.model import Message, Prompt
from ashley.initiative.initiative import Initiative
from initiative_support import speaking
from ashley.people.model import Account, Household, Person
from ashley.people.people import People
from ashley.senses.postgres_wakes import PostgresWakes
from ashley.senses.presence import Presence
from ashley.senses.wakes import Wake, Wakes
from ashley.tools.tools import Tools
from ashley.workshop.commands import Add, Command
from ashley.workshop.model import By, Owner, Text
from ashley.workshop.postgres import PostgresWorkshop
from ashley.workshop.rules import load as workshop_rules
from ashley.workshop.workshop import Workshop
from contract.conversations_support import POLICY, household, person, scalar
from wake_support import Model, Nobody, Switchboard

NAME = "Willow"
ALANA = Person(1, 10, "Alana")
SAM = Person(2, 10, "Sam")
HOME = Household(10, NAME, "America/Denver", "", (ALANA, SAM))
AT = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)
BRIEF = "Greet him only if he has been away a while."


def turn(i: int, author: Author, text: str, speaker: int | None = None, minutes: int = 0) -> Turn:
    return Turn(i, author, speaker, text, AT + timedelta(minutes=minutes))


@dataclass
class OnePerson(People):
    home: Household

    async def household(self, household_id: int) -> Household | None:
        return self.home if household_id == self.home.id else None

    async def person_for(self, system: str, external_id: str) -> Person | None:
        if (system, external_id) == ("home_assistant", "person.alana"):
            return self.home.people[0]
        return None

    async def accounts(self, household_id: int, system: str) -> tuple[Account, ...]:
        return ()


@dataclass
class World:
    url: str
    home: int
    alana: int
    device: int
    model: Model
    tools: Switchboard
    wakes: Wakes
    workshop: Workshop

    async def rule(self, event: str = "alana_arrived") -> None:
        owner = Owner(self.home, self.alana)
        bench = await self.workshop.open(owner, "arrivals")
        body = json.dumps({"event": event, "brief": BRIEF, "tools": ["switch"]})
        command: Command = Add(By(self.alana), "wake", Text("arrival", body), "medium")
        await self.workshop.apply(owner, bench.id, command)

    async def woken(self, event_id: str = "ctx-1", event: str = "alana_arrived") -> int:
        made = await self.wakes.receive(self.device, Wake(self.home, event_id, event, "person.alana", "front_door",
                                                          datetime.now(UTC)))
        return made.id

    def turns(self) -> list[tuple[str, int | None, str | None, str]]:
        """Every stored turn, oldest first: (author, speaker id, source, text)."""
        rows = scalar(self.url, "SELECT coalesce(json_agg(json_build_array(author, speaker_id, source, text) "
                                "ORDER BY id), '[]') FROM turns")
        return [(str(r[0]), None if r[1] is None else int(r[1]), None if r[2] is None else str(r[2]), str(r[3]))
                for r in rows]

    def conversation_of_turns(self) -> list[int]:
        return list(scalar(self.url, "SELECT coalesce(json_agg(DISTINCT conversation_id), '[]') FROM turns"))


@asynccontextmanager
async def world(url: str) -> AsyncGenerator[World]:
    db = PoolDatabase(url, connect_timeout_s=5.0)
    await db.open()
    home = household(url, NAME)
    alana = person(url, home, "Alana")
    device = int(scalar(url, "INSERT INTO devices (household_id, name, place, audience, medium, kind, token_sha256, house) "
                             "VALUES (%s, 'home assistant', 'house', 'household', 'text', 'chat', "
                             "decode(%s, 'hex'), true) RETURNING id", (home, f"{home:064x}")))
    model, tools = Model(), Switchboard()
    made = World(url, home, alana, device, model, tools, PostgresWakes(db), PostgresWorkshop(db, workshop_rules()))
    services.register(People, OnePerson(Household(home, NAME, "America/Denver", "", (Person(alana, home, "Alana"),))))
    services.register(Presence, Nobody())
    services.register(Conversations, PostgresConversations(db, POLICY))
    services.register(InFlight, PostgresInFlight(db, POLICY, 60.0))
    services.register(Outbox, PostgresOutbox(db, 600.0, POLICY))
    services.register(Tools, tools)
    services.register(Inference, model)
    services.register(Wakes, made.wakes)
    services.register(Workshop, made.workshop)
    services.register(Initiative, speaking())
    try:
        yield made
    finally:
        await db.close()


def last_message(prompt: Prompt) -> str:
    return [m.text for m in prompt.messages if isinstance(m, Message)][-1]
