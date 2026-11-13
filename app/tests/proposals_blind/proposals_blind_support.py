"""Pieces of the proposals blind tests: the Postgres proposals store on a migrated database, builders for the four
payload kinds, a person's conversation as a pair of ids, and the tools that propose through the store over a recording
House and a household on a real database."""

import asyncio
import json
from collections.abc import AsyncGenerator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from ashley import services
from psycopg import AsyncConnection
from ashley.db.pool import PoolDatabase
from ashley.home_assistant.automations import NullAutomations
from ashley.home_assistant.change import Change
from ashley.home_assistant.client import connect
from ashley.home_assistant.homes import Home, Homes
from ashley.home_assistant.house import (ActionInfo, ConfigItem, ConfigKind, House, LogEntry, Performed, Record, RecordKind,
                                         Series, State, Window)
from ashley.inference.model import ToolCall, ToolResult, ToolSpec
from ashley.people.model import Account, Household, Person
from ashley.people.people import People
from ashley.senses.deposit_rule import DepositRule
from ashley.senses.postgres_proposals import PostgresProposals
from ashley.senses.postgres_wakes import PostgresWakes
from ashley.senses.proposal_payloads import HouseChange, MoneyRule, Payload, ReminderChange, ReminderSchedule
from ashley.senses.proposals import Proposal, Proposals
from ashley.senses.wakes import Reminder, Wakes
from ashley.tools.house_change import HouseChangeTools
from ashley.tools.reminders import ReminderTools
from ashley.tools.tools import Catalogue, Tools
from contract.conversations_support import household, person

NOW = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
HOUR = 3600.0
TTL = 600.0
BRIEF = "PB-PLANTED-zq water the ferns"
DENVER = ZoneInfo("America/Denver")


def reminder(house: int, who: int, brief: str = BRIEF, due_at: datetime | None = None, by: int | None = None,
             tools: tuple[str, ...] | None = None) -> Reminder:
    return Reminder(house, who, who if by is None else by, brief, clock() + timedelta(hours=2) if due_at is None else due_at,
                    None, tools=tools)


def rule() -> DepositRule:
    return DepositRule("acct-1", "Checking", 10000, "Acme", "contains", "in")


def schedule(house: int, who: int, brief: str = BRIEF, due_at: datetime | None = None) -> ReminderSchedule:
    return ReminderSchedule(reminder(house, who, brief, due_at, tools=("lamp_on",)))


def money(house: int, who: int, brief: str = BRIEF) -> MoneyRule:
    return MoneyRule(reminder(house, who, brief, clock()), rule())


def edit(house: int, who: int, target: int = 5, brief: str = BRIEF) -> ReminderChange:
    return ReminderChange(reminder(house, who, brief), target)


def house_change(summary: str = "Delete the porch automation", id_: str = "porch") -> HouseChange:
    return HouseChange(Change("delete", "automation", id_), summary)


def clock() -> datetime:
    return datetime.now(UTC)


def proposal[P: Payload](payload: P, house: int, who: int, conversation: int = 1, turn: int = 10,
                at: datetime | None = None) -> Proposal[P]:
    return Proposal(house, who, conversation, turn, clock() if at is None else at, payload)


@dataclass
class Store:
    """The Postgres proposals store on a migrated database with one household of Alana and Sam."""

    url: str
    db: PoolDatabase
    store: PostgresProposals
    house: int
    alana: int
    sam: int
    other_house: int
    kim: int


@asynccontextmanager
async def store(url: str) -> AsyncGenerator[Store]:
    db = PoolDatabase(url, connect_timeout_s=5.0)
    await db.open()
    house, other = household(url, "pb"), household(url, "pb-other")
    kept = PostgresProposals(db)
    services.register(Proposals, kept)
    try:
        yield Store(url, db, kept, house, person(url, house, "Alana"), person(url, house, "Sam"), other,
                    person(url, other, "Kim"))
    finally:
        services.unregister(Proposals)
        await db.close()


class RecordingHouse(House):
    """A House that notes each change asked of it."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def offered(self) -> bool:
        return True

    async def states(self) -> tuple[State, ...]:
        return ()

    async def records(self, kind: RecordKind) -> tuple[Record, ...]:
        return ()

    async def history(self, window: Window) -> tuple[Series, ...]:
        return ()

    async def logbook(self, window: Window) -> tuple[LogEntry, ...]:
        return ()

    async def actions(self) -> tuple[ActionInfo, ...]:
        return ()

    async def perform(self, action: str, ids: tuple[str, ...], data: Mapping[str, Any]) -> Performed:
        self.calls.append(("perform", (action, ids, dict(data))))
        return Performed((), None)

    async def configs(self, kind: ConfigKind) -> tuple[ConfigItem, ...]:
        return ()

    async def config(self, kind: ConfigKind, config_id: str) -> Mapping[str, Any] | None:
        return None

    async def write_config(self, kind: ConfigKind, config_id: str | None, config: Mapping[str, Any]) -> str:
        self.calls.append(("write_config", (kind, config_id)))
        return config_id or "new-id"

    async def delete_config(self, kind: ConfigKind, config_id: str) -> bool:
        self.calls.append(("delete_config", (kind, config_id)))
        return True

    async def shown_as(self, kind: ConfigKind, config_id: str) -> str | None:
        raise AssertionError("not used")

    async def set_enabled(self, thing: str, enabled: bool) -> None:
        raise AssertionError("not used")

    async def create_record(self, kind: RecordKind, fields: Mapping[str, Any]) -> str:
        self.calls.append(("create_record", (kind,)))
        return "new"

    async def update_record(self, kind: RecordKind, record_id: str, fields: Mapping[str, Any]) -> None:
        self.calls.append(("update_record", (kind, record_id)))

    async def delete_record(self, kind: RecordKind, record_id: str) -> None:
        self.calls.append(("delete_record", (kind, record_id)))

    async def diagnostics(self, integration_id: str) -> Mapping[str, Any] | None:
        return None


class Folk(People):
    def __init__(self, home: Household) -> None:
        self.home = home

    async def household(self, household_id: int) -> Household | None:
        return self.home if household_id == self.home.id else None

    async def person_for(self, system: str, external_id: str) -> Person | None:
        return None

    async def accounts(self, household_id: int, system: str) -> tuple[Account, ...]:
        return ()


class HouseHomes(Homes):
    def __init__(self, held: dict[int, Home]) -> None:
        self.held = held

    async def of(self, household_id: int) -> Home | None:
        return self.held.get(household_id)

    async def check(self, base_url: str, token: str) -> None:
        return None


@dataclass
class World:
    """A household of Alana and Sam with the proposals store, Wakes, People and a House wired."""

    url: str
    home: int
    alana: int
    sam: int
    proposals: PostgresProposals
    wakes: Wakes
    house: RecordingHouse

    def reminders(self, who: int | None = None, turn: tuple[int, int] | None = (1, 10), shelf: Any = None,
                  private: bool = True) -> ReminderTools:
        usable = None if shelf is None else (lambda: shelf)
        return ReminderTools(self.home, self.alana if who is None else who, private=private, turn=turn, usable=usable)

    def changes(self, who: int | None = None, turn: tuple[int, int] | None = (1, 10),
                ttl_s: float | None = None) -> HouseChangeTools:
        return HouseChangeTools(self.home, self.alana if who is None else who, private=True, turn=turn, ttl_s=ttl_s)


@asynccontextmanager
async def world(url: str) -> AsyncGenerator[World]:
    db = PoolDatabase(url, connect_timeout_s=5.0)
    await db.open()
    home = household(url, "pbw")
    alana, sam = person(url, home, "Alana"), person(url, home, "Sam")
    people = Household(home, "home", DENVER.key, "", (Person(alana, home, "Alana"), Person(sam, home, "Sam")))
    held, proposals, wakes = RecordingHouse(), PostgresProposals(db), PostgresWakes(db)
    services.register(People, Folk(people))
    services.register(Homes, HouseHomes({home: Home(home, connect("http://127.0.0.1:9", "t"), NullAutomations(), held)}))
    services.register(Proposals, proposals)
    services.register(Wakes, wakes)
    try:
        yield World(url, home, alana, sam, proposals, wakes, held)
    finally:
        for interface in (People, Homes, Proposals, Wakes):
            services.unregister(interface)
        await db.close()


class Shelf(Tools):
    """The tools the speaker has in a turn: one that acts."""

    async def catalogue(self) -> Catalogue:
        return Catalogue((ToolSpec("lamp_on", "turn the lamp on", {"type": "object"}, reads=False),), None)

    async def call(self, call: ToolCall) -> ToolResult:
        return ToolResult(call.id, "{}")


def tool_body(result: ToolResult) -> dict[str, Any]:
    out: dict[str, Any] = json.loads(result.content)
    assert isinstance(out, dict)
    return out


async def await_waiters(url: str, count: int, timeout: float = 2.0) -> int:
    """How many backends of this database wait on a lock once `count` do or `timeout` passes: the callers have then
    reached the held lock, or never will."""
    async with await AsyncConnection.connect(url, autocommit=True) as conn:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        seen = 0
        while loop.time() < deadline and seen < count:
            cur = await conn.execute("SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() "
                                     "AND wait_event_type = 'Lock' AND pid <> pg_backend_pid()")
            row = await cur.fetchone()
            seen = int(row[0]) if row else 0
            await asyncio.sleep(0.01)
        return seen
