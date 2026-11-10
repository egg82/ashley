"""The world a fired reminder is answered and pushed in: the contract suite's real turn loop on one database, a household
of Alana and Sam, a recording push sender and their browsers."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from ashley import services
from ashley.channels.outbox import Outbox
from ashley.channels.postgres_outbox import PostgresOutbox
from ashley.channels.push import reminders as push_reminders
from ashley.channels.push.config import load as load_push_config
from ashley.channels.push.sender import Notification, Sender, Sent
from ashley.channels.push.subscriptions import Browser, Subscription, Subscriptions
from ashley.initiative.initiative import Initiative, WorthSaying
from ashley.inference.model import ToolCall, ToolResult, ToolSpec
from ashley.live.live import Live
from ashley.people.model import Account, Household, Person
from ashley.people.people import People
from ashley.senses.postgres_wakes import PostgresWakes
from ashley.senses.wakes import Wakes
from ashley.tools.tools import Catalogue, Tools
from ashley.workshop import rules as workshop_rules
from ashley.workshop.postgres import PostgresWorkshop
from ashley.workshop.workshop import Workshop
from contract.conversations_support import POLICY, person
from contract.test_inflight_resume import World, database
from live_support import FakeLive

LAMP = ToolSpec("lamp_on", "turn the lamp on", {"type": "object"}, reads=False)


@dataclass
class Folk(People):
    home: Household

    async def household(self, household_id: int) -> Household | None:
        return self.home if household_id == self.home.id else None

    async def person_for(self, system: str, external_id: str) -> Person | None:
        return None

    async def accounts(self, household_id: int, system: str) -> tuple[Account, ...]:
        return ()


class House(Tools):
    async def catalogue(self) -> Catalogue:
        return Catalogue((LAMP,), "")

    async def call(self, call: ToolCall) -> ToolResult:
        return ToolResult(call.id, '{"ok": true}')


class FakeSender(Sender):
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    async def send(self, browser: Browser, notification: Notification) -> Sent:
        self.sent.append((browser.endpoint, notification.body))
        return Sent("ok", 201)


class Browsers(Subscriptions):
    def __init__(self) -> None:
        self.rows: list[Subscription] = []

    def give(self, household_id: int, person_id: int) -> None:
        n = len(self.rows) + 1
        self.rows.append(Subscription(n, household_id, person_id, Browser(f"https://fcm.googleapis.com/{person_id}/{n}", "k", "a")))

    async def add(self, household_id: int, person_id: int, browser: Browser) -> None:
        raise AssertionError("not used")

    async def remove(self, person_id: int, endpoint: str) -> None:
        raise AssertionError("not used")

    async def count(self, person_id: int, endpoint: str | None = None) -> tuple[int, bool]:
        raise AssertionError("not used")

    async def of(self, household_id: int, person_id: int) -> tuple[Subscription, ...]:
        return tuple(r for r in self.rows if (r.household_id, r.person_id) == (household_id, person_id))

    async def delivered(self, subscription_id: int) -> None:
        return None

    async def gone(self, subscription_id: int) -> None:
        self.rows = [r for r in self.rows if r.id != subscription_id]


@dataclass
class Stack:
    world: World
    wakes: Wakes
    sender: FakeSender

    @property
    def house(self) -> int:
        return self.world.who.household_id

    @property
    def alana(self) -> int:
        return self.world.who.id

    async def deliver(self) -> int:
        """One pass of the push singleton over fired reminders."""
        return await push_reminders.deliver(self.sender, load_push_config())


@asynccontextmanager
async def stack(world: World) -> AsyncGenerator[Stack]:
    sam = Person(person(world.url, world.who.household_id, "Sam"), world.who.household_id, "Sam")
    async with database(world) as db:
        wakes = PostgresWakes(db)
        services.register(Wakes, wakes)
        services.register(Workshop, PostgresWorkshop(db, workshop_rules.load()))
        services.register(Live, FakeLive())
        services.register(Outbox, PostgresOutbox(db, 600.0, POLICY))
        services.register(Initiative, WorthSaying())
        home = Household(world.who.household_id, "home", "America/Denver", "", (world.who, sam))
        services.register(People, Folk(home))
        for pod in (world.first, world.second):
            holder: Any = pod
            holder.tools = House()
        world.as_pod(world.first)
        sender, browsers = FakeSender(), Browsers()
        for who in (world.who.id, sam.id):
            browsers.give(world.who.household_id, who)
        services.register(Subscriptions, browsers)
        yield Stack(world, wakes, sender)
