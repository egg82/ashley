"""Pieces of the reminders-she-shapes blind tests: a household of Alana, Sam and Kim on a real database in a zone of the
test's choosing, Postgres-backed Wakes and Deposits, a Tools source whose specs say which of them read, and calls on
`ReminderTools` by name."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
import json
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from ashley import services
from ashley.channels.outbox import Outbox
from ashley.channels.postgres_outbox import PostgresOutbox
from ashley.channels.push import reminders as push_reminders
from ashley.channels.push.config import load as load_push_config
from ashley.channels.push.sender import Notification, Sender, Sent
from ashley.channels.push.subscriptions import Browser, Subscription, Subscriptions
from ashley.db.pool import PoolDatabase
from ashley.initiative.initiative import Initiative, WorthSaying
from ashley.inference.reply import Reply
from ashley.live.live import Live
from ashley.inference.model import ToolCall, ToolResult, ToolSpec
from ashley.people.model import Account, Household, Person
from ashley.people.people import People
from ashley.senses.deposit_rule import DepositRule, Landed
from ashley.senses.deposits import Deposits
from ashley.senses.postgres_deposits import PostgresDeposits
from ashley.senses.postgres_proposals import PostgresProposals
from ashley.senses.proposals import Proposals
from ashley.senses.postgres_wakes import PostgresWakes
from ashley.senses.repeat import Repeat
from ashley.senses.wakes import Reminder, Scheduled, Wakes
from ashley.tools.reminders import ReminderTools
from ashley.tools.tools import Catalogue, Tools
from ashley.workshop import rules as workshop_rules
from ashley.workshop.postgres import PostgresWorkshop
from ashley.workshop.workshop import Workshop
from contract.conversations_support import POLICY, household, person, scalar
from contract.test_inflight_resume import World, database
from live_support import FakeLive

DENVER = ZoneInfo("America/Denver")
PHOENIX = ZoneInfo("America/Phoenix")
Route = Literal["phone", "quiet"]
BRIEF = "RSH-PLANTED-zq put the bins out"
READ = ToolSpec("look_up", "look something up", {"type": "object"}, reads=True)
ACT = ToolSpec("lamp_on", "turn the lamp on", {"type": "object"}, reads=False)


def now() -> datetime:
    return datetime.now(UTC)


class Folk(People):
    """One household of the given people in the given zone."""

    def __init__(self, home: Household) -> None:
        self.home = home

    async def household(self, household_id: int) -> Household | None:
        return self.home if household_id == self.home.id else None

    async def person_for(self, system: str, external_id: str) -> Person | None:
        return None

    async def accounts(self, household_id: int, system: str) -> tuple[Account, ...]:
        return ()


class Shelf(Tools):
    """A tool source offering `specs` that records each call."""

    def __init__(self, *specs: ToolSpec) -> None:
        self.specs = specs
        self.called: list[str] = []

    async def catalogue(self) -> Catalogue:
        return Catalogue(self.specs, None)

    async def call(self, call: ToolCall) -> ToolResult:
        self.called.append(call.name)
        return ToolResult(call.id, "{}")


@dataclass
class Home:
    url: str
    house: int
    alana: int
    sam: int
    kim: int
    wakes: Wakes
    deposits: Deposits
    proposals: Proposals
    zone: ZoneInfo

    def reminder(self, who: int | None = None, by: int | None = None, brief: str = BRIEF, due_in_s: float = 3600.0,
                 repeat: Repeat | None = None, **more: Any) -> Reminder:
        who = self.alana if who is None else who
        return Reminder(self.house, who, who if by is None else by, brief, now() + timedelta(seconds=due_in_s), repeat, **more)

    def tools(self, speaker: int | None = None, turn: tuple[int, int] | None = None, private: bool = True,
              shelf: Shelf | None = None) -> ReminderTools:
        usable = None if shelf is None else (lambda: shelf)
        return ReminderTools(self.house, self.alana if speaker is None else speaker, private=private, turn=turn, usable=usable)


@asynccontextmanager
async def home(url: str, zone: ZoneInfo = DENVER) -> AsyncGenerator[Home]:
    db = PoolDatabase(url, connect_timeout_s=5.0)
    await db.open()
    house = household(url, "rsh")
    ids = [person(url, house, n) for n in ("Alana", "Sam", "Kim")]
    people = (Person(ids[0], house, "Alana"), Person(ids[1], house, "Sam"), Person(ids[2], house, "Kim"))
    wakes, deposits, proposals = PostgresWakes(db), PostgresDeposits(db), PostgresProposals(db)
    services.register(People, Folk(Household(house, "home", zone.key, "", people)))
    services.register(Wakes, wakes)
    services.register(Deposits, deposits)
    services.register(Proposals, proposals)
    try:
        yield Home(url, house, ids[0], ids[1], ids[2], wakes, deposits, proposals, zone)
    finally:
        for interface in (People, Wakes, Deposits, Proposals):
            services.unregister(interface)
        await db.close()


async def fired_due(h: Home) -> list[tuple[int, Reminder]]:
    """The due reminders (not house wakes) with their wake ids."""
    return [(d.id, d.wake) for d in await h.wakes.due(50) if isinstance(d.wake, Reminder)]


async def offered(tools: ReminderTools) -> list[str]:
    return [s.name for s in (await tools.catalogue()).specs]


async def use(tools: ReminderTools, name: str, args: dict[str, object] | None = None) -> ToolResult:
    return await tools.call(ToolCall("c1", name, {} if args is None else args))


DONE = Reply(spoken="Time to put the bins out.", text="Time to put the bins out.")
SILENT = Reply(spoken="Nothing to add.", text="Nothing to add.", says="none")
LANDED = Landed(250_000, date(2026, 11, 3), "RSH-Checking", "RSH-Payer")
RULE = DepositRule("acct-1", "RSH-Checking", 100_000, "Acme", "contains")


class Sends(Sender):
    """Every push is recorded as (endpoint, body)."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    async def send(self, browser: Browser, notification: Notification) -> Sent:
        self.sent.append((browser.endpoint, notification.body))
        return Sent("ok", 201)


class Browsers(Subscriptions):
    """One browser per person given, by person id."""

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
class Flow:
    """The `wakes` runner over the real turn loop on one database, with Alana (the world's person) and Sam."""

    world: World
    wakes: Wakes
    deposits: Deposits
    sam: int
    sender: Sends

    @property
    def house(self) -> int:
        return self.world.who.household_id

    @property
    def alana(self) -> int:
        return self.world.who.id

    def reminder(self, **more: Any) -> Reminder:
        return Reminder(self.house, self.alana, self.alana, BRIEF, now() - timedelta(seconds=5), None, **more)

    async def arm_then_fire(self, route: Route, landed: Landed) -> None:
        """A reminder the deposit sense fired from an armed one of the given route."""
        armed = await self.deposits.arm(self.reminder(), RULE)
        assert await self.wakes.edit(self.house, self.alana, armed, self.reminder(route=route)) is True
        assert await self.deposits.fire(armed, "tx-1", landed) is True

    async def pushes(self) -> list[str]:
        """After a delivery pass, the person (as `push:<id>`) behind every browser a notification went to so far."""
        await push_reminders.deliver(self.sender, load_push_config())
        return [f"push:{endpoint.split('/')[3]}" for endpoint, _ in self.sender.sent]

    def hers(self) -> list[str]:
        return self.world.hers()

    def outbox(self) -> int:
        return int(scalar(self.world.url, "SELECT count(*) FROM outbox"))

    async def listed(self) -> list[Scheduled]:
        return [s for s in await self.wakes.reminders(self.house, self.alana) if s.deposit is None]


@asynccontextmanager
async def flow(world: World, initiative: Initiative | None = None) -> AsyncGenerator[Flow]:
    sam = person(world.url, world.who.household_id, "Sam")
    async with database(world) as db:
        wakes, deposits = PostgresWakes(db), PostgresDeposits(db)
        services.register(Wakes, wakes)
        services.register(Deposits, deposits)
        services.register(Workshop, PostgresWorkshop(db, workshop_rules.load()))
        services.register(Live, FakeLive())
        services.register(Outbox, PostgresOutbox(db, 600.0, POLICY))
        services.register(Initiative, initiative or WorthSaying())
        people = (world.who, Person(sam, world.who.household_id, "Sam"))
        services.register(People, Folk(Household(world.who.household_id, "home", "America/Denver", "", people)))
        for pod in (world.first, world.second):
            holder: Any = pod
            holder.tools = Shelf()
        world.as_pod(world.first)
        browsers, sends = Browsers(), Sends()
        for who in (world.who.id, sam):
            browsers.give(world.who.household_id, who)
        services.register(Subscriptions, browsers)
        yield Flow(world, wakes, deposits, sam, sends)


TOMORROW = (datetime.now(UTC) + timedelta(days=30)).date()
AT = f"{TOMORROW.isoformat()}T10:30"


def remind_args(**more: object) -> dict[str, object]:
    return {"for": "Alana", "at": AT, "what": BRIEF, **more}


async def stored(h: Home, who: int | None = None) -> list[Scheduled]:
    return list(await h.wakes.reminders(h.house, h.alana if who is None else who))


def body(result: ToolResult) -> dict[str, Any]:
    out: dict[str, Any] = json.loads(result.content)
    assert isinstance(out, dict)
    return out


async def proposed(h: Home, shelf: Shelf, turn: int = 10, conv: int = 1, **args: object) -> None:
    result = await use(h.tools(turn=(conv, turn), shelf=shelf), "remind", remind_args(**{"tools": ["lamp_on"], **args}))
    assert result.is_error is False and body(result)["armed"] is False
