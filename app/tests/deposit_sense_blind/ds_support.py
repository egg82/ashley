"""Pieces of the deposit-sense blind tests: a fake Sure in the shape real Sure answers (income is a positive
`signed_amount_cents` with classification `income`; a transfer in is income marked `excluded`; a payee is the merchant
when there is one, else the transaction's name), the services the sense reads through, and one household on a real
database."""

import asyncio
from collections.abc import AsyncGenerator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

import psycopg
from ashley import services
from ashley.connections.connections import Connections
from ashley.db.pool import PoolDatabase
from ashley.people.model import Account, Household, Person
from ashley.people.people import People
from ashley.senses.deposit_rule import DepositRule, PayeeMatch
from ashley.senses.deposits import Armed, Deposits
from ashley.senses.postgres_deposits import PostgresDeposits
from ashley.senses.postgres_proposals import PostgresProposals
from ashley.senses.proposals import Proposals
from ashley.senses.postgres_wakes import PostgresWakes
from ashley.senses.wakes import Reminder, Scheduled, Wakes
from ashley.sure.client import Sure, SureFailed
from contract.conversations_support import household, person
from money_support import HeldConnections

CHECKING = "0b6f5a3e-1c2d-4e5f-8a9b-0c1d2e3f4a5b"
SAVINGS = "9c8d7e6f-5a4b-4c3d-8e2f-1a0b9c8d7e6f"
NAMES = {CHECKING: "PlantedChecking-zq", SAVINGS: "PlantedSavings-zq"}
BONUS = "Acme Payroll Planted-zq"
BRIEF = "move the bonus to joint savings"
ARMED_AT = datetime(2026, 10, 20, 18, 0, tzinfo=UTC)
ARMED_DAY = date(2026, 10, 20)
NOW = datetime(2026, 10, 22, 18, 0, tzinfo=UTC)


def tx(id_: str, day: date, cents: int, name: str = "ACH CREDIT 4411", merchant: str | None = None,
       account: str = CHECKING, kind: str = "income", excluded: bool = False, split_parent: bool = False,
       transfer: bool = False) -> dict[str, object]:
    sign = 1 if kind == "income" else -1
    return {"id": id_, "entry_id": "e-" + id_, "date": day.isoformat(), "amount": f"${cents / 100:,.2f}",
            "amount_cents": cents, "signed_amount_cents": sign * cents, "currency": "USD", "name": name,
            "classification": kind, "kind": "funds_movement" if transfer else "standard", "excluded": excluded,
            "split_parent": split_parent,
            "account": {"id": account, "name": NAMES[account], "account_type": "depository"},
            "category": None, "merchant": {"id": "m-" + id_, "name": merchant} if merchant else None, "tags": [],
            "transfer": {"id": "x-" + id_} if transfer else None}


def transfer_in(id_: str, day: date, cents: int) -> dict[str, object]:
    return tx(id_, day, cents, name="Transfer from Savings", excluded=True, transfer=True)


@dataclass
class FakeSure(Sure):
    """The household's transactions, answered the way `GET /api/v1/transactions` does: filtered by the query's
    `start_date`, `end_date`, `account_id` and `classification` when they are sent, paged by `page` and `per_page`.
    `down` makes every call fail as an unreachable Sure; `yields` makes each call give up the event loop first."""

    rows: dict[str, list[dict[str, object]]] = field(default_factory=dict[str, list[dict[str, object]]])
    down: bool = False
    yields: int = 0
    calls: list[tuple[str, Mapping[str, str | int]]] = field(default_factory=list[tuple[str, Mapping[str, str | int]]])

    async def get(self, base: str, api_key: str, path: str, params: Mapping[str, str | int]) -> object:
        self.calls.append((base, dict(params)))
        for _ in range(self.yields):
            await asyncio.sleep(0)
        if self.down:
            raise SureFailed("unreachable")
        if path != "/api/v1/transactions":
            raise SureFailed("not_sure")
        rows = [r for r in self.rows.get(base, []) if self._wanted(r, params)]
        per_page, page = int(params.get("per_page", 25)), int(params.get("page", 1))
        return {"transactions": rows[(page - 1) * per_page: page * per_page],
                "pagination": {"page": page, "per_page": per_page, "total_count": len(rows),
                               "total_pages": max(1, -(-len(rows) // per_page))}}

    async def put(self, base: str, api_key: str, path: str, body: Mapping[str, object]) -> object:
        raise AssertionError("the deposit sense only reads")

    @staticmethod
    def _wanted(row: dict[str, object], params: Mapping[str, str | int]) -> bool:
        day = str(row["date"])
        if "start_date" in params and day < str(params["start_date"]):
            return False
        if "end_date" in params and day > str(params["end_date"]):
            return False
        account = row["account"]
        assert isinstance(account, dict)
        if "account_id" in params and account["id"] != params["account_id"]:
            return False
        return "classification" not in params or row["classification"] == params["classification"]


@dataclass
class Folk(People):
    """A household of Alana and Sam."""

    homes: dict[int, Household]

    async def household(self, household_id: int) -> Household | None:
        return self.homes.get(household_id)

    async def person_for(self, system: str, external_id: str) -> Person | None:
        return None

    async def accounts(self, household_id: int, system: str) -> tuple[Account, ...]:
        return ()


@dataclass
class Folks:
    """One household on a database, its people, its Sure on `base`, and the services wired to a real database."""

    url: str
    house: int
    alana: int
    sam: int
    base: str
    sure: FakeSure
    deposits: Deposits
    wakes: Wakes
    connections: HeldConnections
    folk: Folk

    async def arm(self, rule: DepositRule, at: datetime = ARMED_AT, who: int | None = None, brief: str = BRIEF,
                  made_by: int | None = None) -> int:
        who = self.alana if who is None else who
        return await self.deposits.arm(Reminder(self.house, who, who if made_by is None else made_by, brief, at, None), rule)

    def put(self, *rows: dict[str, object], base: str | None = None) -> None:
        self.sure.rows.setdefault(base or self.base, []).extend(rows)

    async def fired(self, who: int | None = None) -> list[Scheduled]:
        """The ordinary reminders stored beside the armed ones, for `who`."""
        listed = await self.wakes.reminders(self.house, self.alana if who is None else who)
        return [s for s in listed if s.deposit is None]

    async def armed(self) -> tuple[Armed, ...]:
        return await self.deposits.armed()

    def add_house(self, name: str, base: str) -> tuple[int, int]:
        """Another household on the same database, with its own Sure at `base`; its id and its one person's."""
        house = household(self.url, name)
        with psycopg.connect(self.url, autocommit=True) as conn:
            conn.execute("UPDATE households SET timezone = 'America/Denver' WHERE id = %s", (house,))
        who = person(self.url, house, name + "Person")
        self.connections.connect(house, base)
        self.folk.homes[house] = Household(house, name, "America/Denver", "", (Person(who, house, name + "Person"),))
        return house, who


def rule(account: str = CHECKING, min_cents: int | None = 10000, payee: str | None = None,
         match: PayeeMatch = "contains") -> DepositRule:
    return DepositRule(account, NAMES[account], min_cents, payee, match)


def days_ago(n: int, now: datetime = NOW) -> date:
    return (now - timedelta(days=n)).date()


@asynccontextmanager
async def home(url: str, with_sure: bool = True) -> AsyncGenerator[Folks]:
    house = household(url, "one")
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("UPDATE households SET timezone = 'America/Denver' WHERE id = %s", (house,))
    alana, sam = person(url, house, "Alana"), person(url, house, "Sam")
    db = PoolDatabase(url, connect_timeout_s=5.0)
    await db.open()
    base = "https://money.test"
    connections, sure = HeldConnections(), FakeSure()
    if with_sure:
        connections.connect(house, base)
    deposits, wakes = PostgresDeposits(db), PostgresWakes(db)
    folk = Folk({house: Household(house, "one", "America/Denver", "", (Person(alana, house, "Alana"), Person(sam, house, "Sam")))})
    services.register(Deposits, deposits)
    services.register(Proposals, PostgresProposals(db))
    services.register(Wakes, wakes)
    services.register(Connections, connections)
    services.register(Sure, sure)
    services.register(People, folk)
    try:
        yield Folks(url, house, alana, sam, base, sure, deposits, wakes, connections, folk)
    finally:
        for interface in (Deposits, Proposals, Wakes, Connections, Sure, People):
            services.unregister(interface)
        await db.close()
