"""The deposit sense on a real database: a fake Sure whose `/api/v1/transactions` filters, pages and answers in the shape
Sure's jbuilder writes (`money_support`), the household's connection, and Postgres-backed Deposits, Wakes and People."""

import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx2
from ashley import services
from ashley.connections.connections import Connections
from ashley.db.pool import PoolDatabase
from ashley.people.people import People
from ashley.people.postgres import PostgresPeople
from ashley.inference.model import ToolCall, ToolResult
from ashley.senses.deposit_rule import DepositRule
from ashley.senses.deposits import Deposits
from ashley.senses.postgres_deposits import PostgresDeposits
from ashley.senses.postgres_proposals import PostgresProposals
from ashley.senses.proposals import Proposals
from ashley.senses.postgres_wakes import PostgresWakes
from ashley.senses.wakes import Reminder, Wakes
from ashley.sure.client import Sure
from ashley.tools import reminder_specs as specs
from ashley.tools.reminders import ReminderTools
from contract.conversations_support import household, person
from money_support import CHECKING, FakeSure, HeldConnections, account, page, transaction

SAVINGS = "5c4d3e2f-1a0b-4c9d-8e7f-6a5b4c3d2e1f"
BONUS = "Acme Corp Bonus"
NOW = datetime(2026, 11, 3, 15, 0, tzinfo=UTC)


def deposit(id_: str, name: str, cents: int, day: date, merchant: str | None = None, account_id: str = CHECKING,
            classification: str = "income", transfer: bool = False) -> dict[str, object]:
    """A transaction in the shape household 1's real Sure returns: an income row's `signed_amount_cents` is positive,
    an expense's negative, a transfer in is income that is `excluded`, and a row may have no merchant."""
    row = transaction(name, f"${cents / 100:,.2f}", day.isoformat())
    row.update(id=id_, signed_amount_cents=cents if classification == "income" else -cents, amount_cents=cents, classification=classification,
               account={"id": account_id, "name": "Checking", "account_type": "depository"},
               merchant=None if merchant is None else {"id": "m-" + id_, "name": merchant},
               transfer={"id": "x"} if transfer else None)
    return row


@dataclass
class DepositSure(FakeSure):
    """Answers transactions from `rows`, honouring `start_date`, `type`, `per_page` and `page`, newest first."""

    rows: list[dict[str, object]] = field(default_factory=list[dict[str, object]])

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        if request.url.path != "/api/v1/transactions" or self.status != 200:
            return super().handle(request)
        self.seen.append((request.url.path, dict(request.url.params), request.headers.get("x-api-key")))
        q = request.url.params
        found = [r for r in self.rows if str(r["date"]) >= q.get("start_date", "0000-00-00")
                 and (q.get("type") is None or r["classification"] == q["type"])]
        found.sort(key=lambda r: str(r["date"]), reverse=True)
        size, number = int(q.get("per_page", 25)), int(q.get("page", 1))
        body = {"transactions": found[(number - 1) * size:number * size], "pagination": page(len(found))}
        return httpx2.Response(200, content=json.dumps(body).encode(), headers={"content-type": "application/json"})

    def polls(self) -> list[dict[str, str]]:
        return [q for p, q, _ in self.seen if p == "/api/v1/transactions"]


@dataclass
class House:
    url: str
    home: int
    alana: int
    sure: DepositSure
    connections: HeldConnections
    deposits: Deposits
    wakes: Wakes
    proposals: Proposals

    async def arm(self, rule: DepositRule, brief: str = "Your bonus landed: move it to joint savings.",
                  at: datetime = NOW - timedelta(days=1)) -> int:
        return await self.deposits.arm(Reminder(self.home, self.alana, self.alana, brief, at, None), rule)


@asynccontextmanager
async def house(url: str, sure: DepositSure | None = None) -> AsyncGenerator[House]:
    db = PoolDatabase(url, connect_timeout_s=5.0)
    await db.open()
    home = household(url)
    alana = person(url, home, "Alana")
    held = HeldConnections()
    held.connect(home)
    fake = sure or DepositSure(answers={"/api/v1/accounts": {"accounts": [account(CHECKING, "Checking", "$1.00")],
                                                              "pagination": page(1)}})
    deposits, wakes, proposals = PostgresDeposits(db), PostgresWakes(db), PostgresProposals(db)
    services.register(People, PostgresPeople(db))
    services.register(Connections, held)
    services.register(Sure, fake.client())
    services.register(Deposits, deposits)
    services.register(Proposals, proposals)
    services.register(Wakes, wakes)
    try:
        yield House(url, home, alana, fake, held, deposits, wakes, proposals)
    finally:
        for interface in (People, Connections, Sure, Deposits, Proposals, Wakes):
            services.unregister(interface)
        await db.close()


def rule(**fields: Any) -> DepositRule:
    """The planted bonus rule: into checking, at least 1,000.00, from a payee containing `Acme`, with `fields` changed."""
    return replace(DepositRule(CHECKING, "Checking", 100_000, "Acme", "contains"), **fields)


class AnsweringTools(ReminderTools):
    """`ReminderTools` for a person who answers at once: `remind_on_money` proposes in one person turn and arms in the
    next of the same conversation, and returns the armed result (or the proposal's error). Everything else is as is."""

    def __init__(self, household_id: int, speaker_id: int, *, private: bool) -> None:
        super().__init__(household_id, speaker_id, private=private, turn=(1, 1))
        self._later = ReminderTools(household_id, speaker_id, private=private, turn=(1, 2))

    async def call(self, call: ToolCall) -> ToolResult:
        proposed = await super().call(call)
        if call.name != specs.ON_MONEY or proposed.is_error:
            return proposed
        return await self._later.call(ToolCall(call.id + "-arm", specs.ARM, {}))
