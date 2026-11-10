"""A world for the agree-by-tap tests: a migrated database, a household of Alana and Sam, the real stores behind the
locator, a model that fails the test if it is ever asked, and tools that record each call and answer from `answers`."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from ashley import services
from ashley.channels.model import Inbound
from ashley.channels.outbox import Outbox
from ashley.channels.postgres_outbox import PostgresOutbox
from ashley.conversations.conversations import Conversations
from ashley.conversations.inflight import InFlight
from ashley.conversations.model import NewTurn
from ashley.conversations.postgres import PostgresConversations
from ashley.conversations.postgres_inflight import PostgresInFlight
from ashley.db.pool import PoolDatabase
from ashley.inference.inference import Inference
from ashley.inference.model import ToolCall, ToolResult, ToolSpec
from ashley.people.model import Account, Household, Person
from ashley.people.people import People
from ashley.senses.postgres_proposals import PostgresProposals
from ashley.senses.proposal_payloads import HeldCall, HeldCalls
from ashley.senses.proposals import Proposal, Proposals
from ashley.senses.presence import Presence
from ashley.tools.tools import Catalogue, Tools
from contract.conversations_support import POLICY, household, person
from wake_support import Model, Nobody

SWITCH = ToolSpec("switch", "turn something on", {"type": "object"}, reads=False)
OPEN = ToolSpec("open_door", "open a door", {"type": "object"}, reads=False)
HELD = (HeldCall("switch", {"lamp": "hall"}, 'switch (lamp: "hall")'),
        HeldCall("open_door", {"door": "garage"}, 'open_door (door: "garage")'),
        HeldCall("vanished", {}, "vanished"))


@dataclass
class Home(People):
    home: Household

    async def household(self, household_id: int) -> Household | None:
        return self.home if household_id == self.home.id else None

    async def person_for(self, system: str, external_id: str) -> Person | None:
        return None

    async def accounts(self, household_id: int, system: str) -> tuple[Account, ...]:
        return ()


@dataclass
class Recording(Tools):
    """`ran` is every call that reached a tool; a tool named in `answers` answers that, else `ok`."""

    ran: list[ToolCall] = field(default_factory=list[ToolCall])
    answers: dict[str, ToolResult] = field(default_factory=dict[str, ToolResult])

    async def catalogue(self) -> Catalogue:
        return Catalogue((SWITCH, OPEN), "")

    async def call(self, call: ToolCall) -> ToolResult:
        self.ran.append(call)
        got = self.answers.get(call.name)
        return ToolResult(call.id, "ok") if got is None else ToolResult(call.id, got.content, got.is_error, outside=got.outside)


@dataclass
class World:
    url: str
    db: PoolDatabase
    home: int
    alana: int
    sam: int
    tools: Recording
    model: Model
    proposals: PostgresProposals
    conversations: PostgresConversations

    @property
    def thread(self) -> str:
        return f"person:{self.alana}:web"

    async def hold(self, calls: tuple[HeldCall, ...] = HELD, who: int | None = None, age: timedelta = timedelta(0)) -> int:
        """Her turn held `calls` for `who` (Alana): the person turn it answered stored, then the proposal; its id."""
        by = who or self.alana
        conversation = await self.conversations.for_thread(self.home, f"person:{by}:web", "chat", [by], remembered=True,
                                                           channel="web", place=None)
        said = await self.conversations.add_turn(conversation.id, NewTurn("person", "do the thing", by, "private", by))
        return await self.proposals.propose(Proposal(self.home, by, conversation.id, said.id,
                                                     datetime.now(UTC) - age, HeldCalls(calls)), 10**9)

    def tap(self, proposal_id: int, who: int | None = None) -> Inbound:
        by = who or self.alana
        return Inbound(household_id=self.home, thread=f"person:{by}:web", text="", kind="chat", medium="text",
                       audience="owner", speaker_id=by, shared=False, place=None, channel="web", later=True,
                       later_by="turn", on_page=True, taint=None, agree=proposal_id)


@asynccontextmanager
async def world(url: str) -> AsyncGenerator[World]:
    db = PoolDatabase(url, connect_timeout_s=5.0)
    await db.open()
    home = household(url)
    alana, sam = person(url, home, "Alana"), person(url, home, "Sam")
    tools, model = Recording(), Model()
    conversations, proposals = PostgresConversations(db, POLICY), PostgresProposals(db)
    services.register(People, Home(Household(home, "home", "America/Denver", "", (Person(alana, home, "Alana"),
                                                                                    Person(sam, home, "Sam")))))
    services.register(Presence, Nobody())
    services.register(Conversations, conversations)
    services.register(InFlight, PostgresInFlight(db, POLICY, 60.0))
    services.register(Outbox, PostgresOutbox(db, 600.0, POLICY))
    services.register(Proposals, proposals)
    services.register(Tools, tools)
    services.register(Inference, model)
    try:
        yield World(url, db, home, alana, sam, tools, model, proposals, conversations)
    finally:
        await db.close()
