"""Shared pieces of the reminder blind tests: reminder builders on the household's wall clock, a real Wakes on one
database, the `wakes` runner stack over the real turn loop with a household of Alana and Sam, and SQL to read the outbox."""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from ashley import services
from ashley.channels.outbox import Outbox
from ashley.channels.postgres_outbox import PostgresOutbox
from ashley.channels.push import reminders as push_reminders
from ashley.channels.push.config import load as load_push_config
from ashley.channels.push.sender import Notification, Sender, Sent
from ashley.channels.push.subscriptions import Browser, Subscription, Subscriptions
from ashley.db.pool import PoolDatabase
from ashley.initiative.initiative import Initiative
from initiative_support import speaking
from ashley.inference.model import ToolCall, ToolResult, ToolSpec
from ashley.inference.reply import Reply
from ashley.live.live import Live
from ashley.people.model import Account, Household, Person
from ashley.people.people import People
from ashley.senses.postgres_wakes import PostgresWakes
from ashley.senses.repeat import Repeat
from ashley.senses.wakes import Outcome, Reminder, Route, SaidBefore, Wakes
from ashley.tools.tools import Catalogue, Tools
from ashley.workshop import rules as workshop_rules
from ashley.workshop.postgres import PostgresWorkshop
from ashley.workshop.workshop import Workshop
from contract.conversations_support import POLICY, household, person, scalar
from contract.test_inflight_resume import World, database
from live_support import FakeLive

ZONE = ZoneInfo("America/Denver")
PLANTED = "PLANTED-VISA-zq pay 500 dollars"
DONE = Reply(spoken="Time to pay the Visa.", text="Time to pay the Visa.")
SECOND = Reply(spoken="Second answer.", text="Second answer.")
LAMP = ToolSpec("lamp_on", "turn the lamp on", {"type": "object"}, reads=False)



class Home:
    def __init__(self, url: str) -> None:
        self.url = url
        self.one = household(url, "one")
        self.two = household(url, "two")
        self.alana = person(url, self.one, "Alana")
        self.sam = person(url, self.one, "Sam")
        self.kim = person(url, self.one, "Kim")
        self.other = person(url, self.two, "Other")

    def rows(self) -> int:
        return int(scalar(self.url, "SELECT count(*) FROM wakes"))


def now() -> datetime:
    return datetime.now(UTC)


def reminder(house: int, who: int, by: int | None = None, brief: str = PLANTED, due_in_s: float = -5.0,
             repeat: Repeat | None = None, due_at: datetime | None = None) -> Reminder:
    return Reminder(house, who, who if by is None else by, brief, due_at or now() + timedelta(seconds=due_in_s), repeat)


def monthly_first(months_back: int, every: int = 1) -> Repeat:
    """Monthly on the 1st at 09:00 Denver, first occurring `months_back` months before the current month."""
    local = now().astimezone(ZONE)
    index = local.year * 12 + local.month - 1 - months_back
    return Repeat("monthly", every, datetime(index // 12, index % 12 + 1, 1, 9, 0))


@asynccontextmanager
async def wakes(url: str) -> AsyncGenerator[Wakes]:
    db = PoolDatabase(url, connect_timeout_s=5.0)
    await db.open()
    try:
        yield PostgresWakes(db)
    finally:
        await db.close()


@dataclass
class Folk(People):
    """A household of the world's person and Sam."""

    home: Household

    async def household(self, household_id: int) -> Household | None:
        return self.home if household_id == self.home.id else None

    async def person_for(self, system: str, external_id: str) -> Person | None:
        return None

    async def accounts(self, household_id: int, system: str) -> tuple[Account, ...]:
        return ()


@dataclass
class House(Tools):
    ran: list[ToolCall] = field(default_factory=list[ToolCall])

    async def catalogue(self) -> Catalogue:
        return Catalogue((LAMP,), "")

    async def call(self, call: ToolCall) -> ToolResult:
        self.ran.append(call)
        return ToolResult(call.id, '{"ok": true}')


class FakeSender(Sender):
    """Every send is recorded as (endpoint, body); the next sends answer `outcome`."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []
        self.outcome: Sent = Sent("ok", 201)

    async def send(self, browser: Browser, notification: Notification) -> Sent:
        self.sent.append((browser.endpoint, notification.body))
        return self.outcome


class FakeSubscriptions(Subscriptions):
    """The browsers each person has, by person id; `gone` forgets one."""

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


class KillableWakes(Wakes):
    """A Wakes that hangs in `settle` while `hang` is set, as a runner killed between its answer and settling."""

    def __init__(self, inner: Wakes) -> None:
        self.inner = inner
        self.hang = False
        self.at_settle = asyncio.Event()

    async def receive(self, device_id: int, wake: Any) -> Any:
        return await self.inner.receive(device_id, wake)

    async def schedule(self, reminder: Reminder) -> int:
        return await self.inner.schedule(reminder)

    async def due(self, limit: int) -> Any:
        return await self.inner.due(limit)

    async def settle(self, wake_id: int, outcome: Outcome, next_due: datetime | None = None) -> bool:
        if self.hang:
            self.at_settle.set()
            await asyncio.Event().wait()
        return await self.inner.settle(wake_id, outcome, next_due)

    async def reminders(self, household_id: int, person_id: int) -> Any:
        return await self.inner.reminders(household_id, person_id)

    async def cancel(self, household_id: int, person_id: int, wake_id: int) -> bool:
        return await self.inner.cancel(household_id, person_id, wake_id)

    async def edit(self, household_id: int, person_id: int, wake_id: int, changed: Reminder) -> bool:
        return await self.inner.edit(household_id, person_id, wake_id, changed)

    async def prune(self, older_than_s: float) -> int:
        return await self.inner.prune(older_than_s)

    async def refire(self, wake_id: int, after_s: float) -> int:
        return await self.inner.refire(wake_id, after_s)

    async def undelivered(self, limit: int, retry_s: float, within_s: float, *, at: Route = "phone", device_tries: int = 0,
                          device_retry_s: float = 0.0) -> Any:
        return await self.inner.undelivered(limit, retry_s, within_s, at=at, device_tries=device_tries,
                                            device_retry_s=device_retry_s)

    async def claim(self, wake_id: int, retry_s: float, *, at: Route = "phone", device_tries: int = 0,
                    device_retry_s: float = 0.0) -> bool:
        return await self.inner.claim(wake_id, retry_s, at=at, device_tries=device_tries,
                                      device_retry_s=device_retry_s)

    async def delivered(self, wake_id: int, reached: bool) -> None:
        await self.inner.delivered(wake_id, reached)

    async def dismiss(self, household_id: int, person_id: int, wake_id: int) -> bool:
        return await self.inner.dismiss(household_id, person_id, wake_id)

    async def said_before(self, wake_id: int, person_id: int) -> SaidBefore:
        return await self.inner.said_before(wake_id, person_id)


@dataclass
class Stack:
    world: World
    wakes: KillableWakes
    sam: Person
    sender: FakeSender
    subs: FakeSubscriptions

    @property
    def house(self) -> int:
        return self.world.who.household_id

    @property
    def alana(self) -> int:
        return self.world.who.id

    async def schedule(self, **kw: Any) -> int:
        return await self.wakes.schedule(reminder(self.house, kw.pop("who", self.alana), **kw))

    async def deliver(self) -> int:
        """One pass of the push singleton over fired reminders."""
        return await push_reminders.deliver(self.sender, load_push_config())

    async def pushes(self) -> list[str]:
        """After a delivery pass, the person (as `push:<id>`) behind every browser a notification was sent to so far."""
        await self.deliver()
        return [f"push:{endpoint.split('/')[3]}" for endpoint, _ in self.sender.sent]

    def outbox(self) -> int:
        """Rows in the outbox: a reminder's push never goes through it."""
        return int(scalar(self.world.url, "SELECT count(*) FROM outbox"))

    def hers(self) -> list[str]:
        return self.world.hers()

    def unsettled(self) -> int:
        return int(scalar(self.world.url, "SELECT count(*) FROM wakes WHERE outcome IS NULL"))


@asynccontextmanager
async def stack(world: World, initiative: Initiative | None = None) -> AsyncGenerator[Stack]:
    sam = Person(person(world.url, world.who.household_id, "Sam"), world.who.household_id, "Sam")
    async with database(world) as db:
        wakes = KillableWakes(PostgresWakes(db))
        services.register(Wakes, wakes)
        services.register(Workshop, PostgresWorkshop(db, workshop_rules.load()))
        services.register(Live, FakeLive())
        services.register(Outbox, PostgresOutbox(db, 600.0, POLICY))
        services.register(Initiative, initiative or speaking())
        home = Household(world.who.household_id, "home", "America/Denver", "", (world.who, sam))
        services.register(People, Folk(home))
        for pod in (world.first, world.second):
            holder: Any = pod
            holder.tools = House()
        world.as_pod(world.first)
        sender, subs = FakeSender(), FakeSubscriptions()
        for who in (world.who.id, sam.id):
            subs.give(world.who.household_id, who)
        services.register(Subscriptions, subs)
        yield Stack(world, wakes, sam, sender, subs)
