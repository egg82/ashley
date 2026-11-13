"""A fake Sure behind `httpx2.MockTransport`, answering Sure's REST shapes (we-promise/sure `app/views/api/v1/*`), the
production wiring (`register_sure`) over it, and the real Postgres-backed Connections holding households' Sure
connections. Every request is recorded with its method, path, query and key."""

import asyncio
import json
import os
from collections.abc import AsyncGenerator, Callable, Coroutine
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import httpx2
import psycopg
from ashley import services
from ashley.connections.connections import Connections, ConnectionsUnavailable, NullConnections
from ashley.connections.model import Connection, Holder, Kind, Opened
from ashley.connections.postgres import PostgresConnections
from ashley.connections.sealing import Sealer
from ashley.db.database import Database
from ashley.db.pool import PoolDatabase
from ashley.ledger.ledger import Ledger
from ashley.sure.register import register
from contract.conversations_support import household, scalar
from connection_legacy_support import put_of

BASE = "https://money.test"
KEY = "the-households-test-key"
OTHER_BASE = "https://other.test"
OTHER_KEY = "the-other-households-key"
CHECKING = "0b6f5a3e-1c2d-4e5f-8a9b-0c1d2e3f4a5b"
GROCERIES = "7d1e2f3a-4b5c-4d6e-8f70-81a2b3c4d5e6"
TIMEOUT_S = 3.5
PAYEE = "Quixotic Pawn Shoppe"
AMOUNT = "$12.34"

Seen = tuple[str, str, dict[str, str], str | None, str]


def account(id_: str, name: str, balance: str, classification: str = "asset") -> dict[str, object]:
    cents = round(float(balance.replace("$", "").replace(",", "")) * 100)
    return {"id": id_, "name": name, "balance": balance, "balance_cents": cents, "cash_balance": balance,
            "currency": "USD", "classification": classification, "account_type": "depository",
            "subtype": "checking", "status": "active", "institution_name": "Bank"}


def transaction(name: str = "Groceries run", amount: str = AMOUNT, day: str = "2026-10-30") -> dict[str, object]:
    return {"id": "t-" + name, "entry_id": "e-" + name, "date": day, "amount": amount, "amount_cents": 1234,
            "signed_amount_cents": -1234, "amount_decimal": "12.34", "currency": "USD", "name": name, "notes": None,
            "classification": "expense", "kind": "standard", "excluded": False, "split_parent": False,
            "account": {"id": CHECKING, "name": "Checking", "account_type": "depository"},
            "category": {"id": GROCERIES, "name": "Groceries", "color": "#00f"},
            "merchant": {"id": "m1", "name": PAYEE}, "tags": [], "transfer": None}


def pagination(total: int) -> dict[str, object]:
    return {"page": 1, "per_page": 25, "total_count": total, "total_pages": 1}


def bodies() -> dict[str, object]:
    return {
        "/api/v1/accounts": {"accounts": [account(CHECKING, "Checking", "$1,234.56"),
                                          account("a2", "Visa", "-$300.00", "liability")],
                             "pagination": pagination(7)},
        "/api/v1/transactions": {"transactions": [transaction()], "pagination": pagination(41)},
        "/api/v1/categories": {"categories": [
            {"id": GROCERIES, "name": "Groceries", "color": "#00f", "parent": {"id": "p1", "name": "Food"}},
            {"id": "c2", "name": "Rent", "parent": None}], "pagination": pagination(2)},
        "/api/v1/balance_sheet": {"currency": "USD",
                                  "net_worth": {"amount": "934.56", "currency": "USD", "formatted": "$934.56"},
                                  "assets": {"amount": "1234.56", "currency": "USD", "formatted": "$1,234.56"},
                                  "liabilities": {"amount": "300.0", "currency": "USD", "formatted": "$300.00"}},
    }


@dataclass
class FakeSure:
    """`status` answers every request with that status; `raw` with that body instead of JSON; `down` raises a
    connection error. Only `key` is accepted (401 otherwise);"""

    key: str = KEY
    status: int = 200
    raw: bytes | None = None
    down: bool = False
    answers: dict[str, object] = field(default_factory=bodies)
    seen: list[Seen] = field(default_factory=list[Seen])
    timeouts: list[set[float]] = field(default_factory=list[set[float]])

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        key = request.headers.get("x-api-key")
        given: dict[str, float] = json.loads(json.dumps(request.extensions.get("timeout") or {}))
        self.timeouts.append(set(given.values()))
        self.seen.append((request.method, request.url.path, dict(request.url.params), key, request.url.host))
        if self.down:
            raise httpx2.ConnectError("down", request=request)
        if self.status != 200:
            return httpx2.Response(self.status, headers={"location": "https://elsewhere.test/"})
        if key not in (self.key, OTHER_KEY):
            return httpx2.Response(401, json={"error": "unauthorized"})
        if self.raw is not None:
            return httpx2.Response(200, content=self.raw, headers={"content-type": "text/html"})
        body = self.answers.get(request.url.path)
        if body is None:
            return httpx2.Response(404, json={"error": "not_found"})
        return httpx2.Response(200, content=json.dumps(body).encode(), headers={"content-type": "application/json"})

    def asked(self, path: str) -> dict[str, str]:
        return next(q for _, p, q, _, _ in self.seen if p == path)


@dataclass
class World:
    url: str
    sure: FakeSure
    database: Database
    connections: Connections
    ledger: Ledger
    household_id: int
    person_id: int

    def checked_at(self, household_id: int | None = None) -> object:
        return scalar(self.url, "SELECT checked_at FROM connections WHERE household_id = %s",
                      (household_id or self.household_id,))

    def age(self, household_id: int | None = None) -> object:
        """Push the connection's `checked_at` a day into the past and return it."""
        return scalar(self.url, "UPDATE connections SET checked_at = now() - interval '1 day' "
                                "WHERE household_id = %s RETURNING checked_at", (household_id or self.household_id,))


def other_household(url: str, name: str = "other") -> tuple[int, int]:
    hid = household(url, name)
    pid = int(scalar(url, "INSERT INTO people (household_id, name) VALUES (%s, 'x') RETURNING id", (hid,)))
    return hid, pid


class AnswerLost(Connections):
    """The household's Connections, except that recording an answer fails."""

    def __init__(self, real: Connections) -> None:
        self._real = real

    @classmethod
    def null(cls) -> Connections:
        return NullConnections()

    def can_open(self) -> bool:
        return self._real.can_open()

    async def of_household(self, household_id: int, person_id: int | None = None) -> tuple[Connection, ...]:
        return await self._real.of_household(household_id, person_id)

    async def opened(self, connection_id: int, household_id: int, person_id: int | None = None) -> Opened | None:
        return await self._real.opened(connection_id, household_id, person_id)

    async def add(self, household_id: int, kind: Kind, label: str, base_url: str, secret: str,
                  added_by: int, holder: Holder | None = None) -> Connection:
        return await self._real.add(household_id, kind, label, base_url, secret, added_by, holder)

    async def replace(self, connection_id: int, household_id: int, person_id: int, base_url: str,
                      secret: str) -> Connection | None:
        return await self._real.replace(connection_id, household_id, person_id, base_url, secret)

    async def relabel(self, connection_id: int, household_id: int, person_id: int,
                      label: str) -> Connection | None:
        return await self._real.relabel(connection_id, household_id, person_id, label)

    async def seed(self, household_id: int, kind: Kind, base_url: str, secret: str) -> Connection | None:
        return await self._real.seed(household_id, kind, base_url, secret)

    async def remove(self, connection_id: int, household_id: int, person_id: int | None) -> bool:
        return await self._real.remove(connection_id, household_id, person_id)

    async def answered(self, connection_id: int) -> None:
        raise ConnectionsUnavailable("down")


@asynccontextmanager
async def world(url: str, sure: FakeSure | None = None, connect: bool = True) -> AsyncGenerator[World]:
    """Postgres Connections holding household 1's Sure connection (unless `connect` is False), the production
    registration of Sure's port and Ledger over a fake Sure, and the Ledger the locator answers."""
    fake = sure or FakeSure()
    database: Database = PoolDatabase(url)
    await database.open()
    http = httpx2.AsyncClient(transport=httpx2.MockTransport(fake.handle), follow_redirects=False)
    try:
        connections = PostgresConnections(database, Sealer({1: os.urandom(32)}, current=1))
        services.register(Connections, connections)
        services.unregister(Ledger)
        register(http, TIMEOUT_S)
        household(url, "pad")
        hid, pid = other_household(url, "home")
        if connect:
            await put_of(connections, hid, "sure", BASE, KEY, pid)
        yield World(url, fake, database, connections, services.get(Ledger), hid, pid)
    finally:
        await http.aclose()
        await database.close()


def run(url: str, scenario: Callable[[World], Coroutine[Any, Any, None]], sure: FakeSure | None = None,
        connect: bool = True) -> FakeSure:
    fake = sure or FakeSure()

    async def go() -> None:
        async with world(url, fake, connect) as w:
            await scenario(w)

    asyncio.run(go())
    return fake


def count(url: str, query: str, params: tuple[object, ...] = ()) -> int:
    with psycopg.connect(url, autocommit=True) as conn:
        row = conn.execute(query.encode(), params).fetchone()
    assert row is not None
    return int(row[0])
