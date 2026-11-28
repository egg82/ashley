"""Contract for `GET /api/find` and `ashley.find.find`, from their docstrings and the defaults of #256's fit pass: each
source answers under its own access rule for the hearer, over real Postgres memory and conversations and planted print
and ledger backends; another person's private row never comes back, nor the ledger to a hearer not reading alone; a
source that fails is named unreachable while the others answer."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

import httpx
from ashley import services
from ashley.api.find_models import FindResults
from ashley.api.person import person_signed_in
from ashley.conversations.conversations import Conversations
from ashley.conversations.model import Hearer, NewTurn
from ashley.db.pool import PoolDatabase
from ashley.find.find import find
from ashley.find.model import Findings
from ashley.find.sources import everyday
from ashley.ledger import model as ledger
from ashley.ledger.ledger import Ledger, NullLedger
from ashley.main import create_app
from ashley.memory.memory import Memory
from ashley.memory.model import Add
from ashley.memory.postgres import PostgresMemory
from ashley.people.model import Person
from ashley.printing import model as printing
from ashley.printing.printing import NullPrinting, Printing
from ashley.settings import Settings
from ashley.signin.model import SignedIn
from conversations_support import household, person, run, service
from memory_contract_support import new_fact

PUBLIC = "https://ashley.test"
WORD = "zeppelin"


@dataclass
class PlantedLedger(NullLedger):
    rows: tuple[ledger.Entry, ...] = ()
    fails: bool = False
    asked: list[int] = field(default_factory=list[int])

    async def transactions(self, household_id: int, query: ledger.TransactionQuery) -> ledger.Page[ledger.Entry]:
        self.asked.append(household_id)
        if self.fails:
            raise ledger.LedgerUnavailable()
        return ledger.Page(self.rows, len(self.rows))


@dataclass
class PlantedPrinting(NullPrinting):
    rows: tuple[printing.PrintFile, ...] = ()
    fails: bool = False

    async def files(self, household_id: int, search: str | None, limit: int) -> printing.Page[printing.PrintFile]:
        if self.fails:
            raise printing.PrintingFailed("unreachable")
        return printing.Page(self.rows, len(self.rows))


def entry(tid: str) -> ledger.Entry:
    return ledger.Entry(tid, "2026-11-02", f"{WORD} tours", "-$40.00", 4000, "expense", "a1", "Checking", None, None,
                        False, False, False)


@dataclass
class World:
    client: httpx.AsyncClient
    conversations: Conversations
    memory: PostgresMemory
    home: int
    alana: Person
    sam: Person
    ledger: PlantedLedger
    printing: PlantedPrinting

    async def fact(self, conversation: int, owner: int | None, text: str, visibility: str = "shared",
                   household_id: int | None = None) -> int:
        made = new_fact(owner, owner, text, "private" if visibility == "private" else "shared")
        ids = await self.memory.apply(household_id or self.home, conversation, [Add(made)], datetime.now(UTC))
        return ids[0]

    async def say(self, conversation: int, speaker: Person, text: str, private_to: Person | None = None) -> int:
        turn = await self.conversations.add_turn(conversation, NewTurn(
            "person", text, speaker.id, "shared" if private_to is None else "private",
            None if private_to is None else private_to.id))
        return turn.id

    async def found(self) -> FindResults:
        got = await self.client.get("/api/find", params={"q": WORD})
        assert got.status_code == 200, got.text
        return FindResults.model_validate(got.json())


def refs(found: FindResults | Findings, kind: str) -> set[str]:
    return {f.ref for f in found.found if f.kind == kind}


@asynccontextmanager
async def world(url: str) -> AsyncGenerator[World]:
    home = household(url)
    alana = Person(person(url, home, "Alana"), home, "Alana")
    sam = Person(person(url, home, "Sam"), home, "Sam")
    app = create_app(Settings(database_url="", build_version="t", public_url=PUBLIC))
    app.dependency_overrides[person_signed_in] = lambda: SignedIn(1, alana)
    db = PoolDatabase(url)
    await db.open()
    planted = (PlantedLedger((entry("t1"),)), PlantedPrinting((printing.PrintFile("p1", f"{WORD} hull", "3mf", None,
                                                                                    None, None, 0),)))
    try:
        async with service(url) as conversations:
            memory = PostgresMemory(db)
            services.register(Conversations, conversations)
            services.register(Memory, memory)
            services.register(Ledger, planted[0])
            services.register(Printing, planted[1])
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=PUBLIC) as client:
                yield World(client, conversations, memory, home, alana, sam, *planted)
    finally:
        await db.close()


def test_a_person_reading_alone_finds_each_source_but_never_anothers_private_row(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            kitchen = await w.conversations.start(w.home, "chat", [w.alana.id, w.sam.id], channel="device")
            mine = await w.say(kitchen.id, w.alana, f"the {WORD} is in the garage")
            await w.say(kitchen.id, w.sam, f"a {WORD} said only to sam", private_to=w.sam)
            elsewhere = await w.conversations.start(w.home, "chat", [w.sam.id])
            await w.say(elsewhere.id, w.sam, f"sam alone with the {WORD}")
            shared = await w.fact(kitchen.id, None, f"The {WORD} lives in the garage.")
            own_private = await w.fact(kitchen.id, w.alana.id, f"Alana keeps a {WORD} diary.", "private")
            await w.fact(kitchen.id, w.sam.id, f"Sam is saving for a {WORD} ride.", "private")
            other_home = household(db_url, "other")
            there = await w.conversations.start(other_home, "chat", [])
            await w.fact(there.id, None, f"Their {WORD} is red.", household_id=other_home)

            got = await w.found()

            assert refs(got, "memory") == {str(shared), str(own_private)}
            assert refs(got, "conversation") == {str(mine)}
            assert {f.within for f in got.found if f.kind == "conversation"} == {str(kitchen.id)}
            assert refs(got, "print") == {"p1"} and refs(got, "transaction") == {"t1"}
            assert [f.dated for f in got.found if f.kind == "transaction"] == [date(2026, 11, 2)]
            assert got.answered == ["memory", "conversation", "print", "transaction"] and got.unreachable == []

    run(scenario())


def test_a_hearer_not_alone_never_gets_the_ledger_or_their_private_rows(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            chat = await w.conversations.start(w.home, "chat", [w.alana.id])
            await w.say(chat.id, w.alana, f"my {WORD} plans")
            shared = await w.fact(chat.id, None, f"The {WORD} lives in the garage.")
            await w.fact(chat.id, w.alana.id, f"Alana keeps a {WORD} diary.", "private")

            on_a_screen = await find(everyday(), Hearer(w.home, w.alana.id, owner_only=False), WORD, 20)
            assert refs(on_a_screen, "memory") == {str(shared)}
            assert on_a_screen.answered == ("memory", "print") and refs(on_a_screen, "print") == {"p1"}

            unknown = await find(everyday(), Hearer(w.home, None, owner_only=False), WORD, 20)
            assert refs(unknown, "memory") == {str(shared)} and unknown.answered == ("memory",)
            assert w.ledger.asked == []

    run(scenario())


def test_a_failing_source_is_unreachable_and_the_others_still_answer(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            chat = await w.conversations.start(w.home, "chat", [w.alana.id])
            said = await w.say(chat.id, w.alana, f"my {WORD} plans")
            known = await w.fact(chat.id, None, f"The {WORD} lives in the garage.")
            w.printing.fails = True
            w.ledger.fails = True

            got = await w.found()

            assert got.unreachable == ["print", "transaction"]
            assert got.answered == ["memory", "conversation"]
            assert refs(got, "memory") == {str(known)} and refs(got, "conversation") == {str(said)}

    run(scenario())
