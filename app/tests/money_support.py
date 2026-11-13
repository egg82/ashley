"""A fake Sure behind `httpx2.MockTransport`, answering `/api/v1/{accounts,transactions,categories,balance_sheet}` in
the shapes Sure's jbuilder views write (we-promise/sure 117bea5d, `app/views/api/v1/*`), one category at
`/api/v1/categories/:id`, and `PUT /api/v1/transactions/:id` as `Api::V1::TransactionsController#update` answers it
(131e786: 404 `not_found` for an id not the household's, 422 for a split's part, 403 `insufficient_scope` for a key that
may only read), and an in-memory Connections holding one household's Sure. Every request is recorded with its path,
query and key, and every PUT with its body, so a test can see what was asked and with what."""

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx2
from ashley import services
from ashley.connections.connections import Connections, ConnectionsUnavailable
from ashley.connections.kinds import ConnectionKinds
from ashley.connections.model import Connection, Holder, Kind, Opened
from ashley.sure.client import HttpSure

BASE = "https://money.test"
KEY = "the-households-test-key"
EPOCH = datetime(2026, 10, 31, tzinfo=UTC)
CHECKING = "0b6f5a3e-1c2d-4e5f-8a9b-0c1d2e3f4a5b"
GROCERIES = "7d1e2f3a-4b5c-4d6e-8f70-81a2b3c4d5e6"


def account(id_: str, name: str, balance: str, classification: str = "asset") -> dict[str, object]:
    """An account as Sure's jbuilder writes it; `balance` as Sure formats dollars ("$1,234.56", "-$5.00")."""
    cents = round(float(balance.replace("$", "").replace(",", "")) * 100)
    return {"id": id_, "name": name, "balance": balance, "balance_cents": cents, "cash_balance": balance,
            "cash_balance_cents": cents, "currency": "USD", "classification": classification, "account_type": "depository",
            "subtype": "checking", "status": "active", "institution_name": "Bank", "institution_domain": "bank.test",
            "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-10-30T00:00:00Z"}


def transaction(name: str, amount: str, day: str, category: dict[str, object] | None = None,
                transfer: dict[str, object] | None = None) -> dict[str, object]:
    return {"id": "t-" + name, "entry_id": "e-" + name, "date": day, "amount": amount, "amount_cents": 1234,
            "signed_amount_cents": -1234, "amount_decimal": "12.34", "currency": "USD", "name": name, "notes": None,
            "external_id": None, "source": None, "user_modified": False, "classification": "expense",
            "kind": "standard", "excluded": False, "split_parent": False,
            "account": {"id": CHECKING, "name": "Checking", "account_type": "depository"},
            "category": category, "merchant": {"id": "m1", "name": "Corner Grocer"}, "tags": [], "transfer": transfer,
            "created_at": "2026-10-01T00:00:00Z", "updated_at": "2026-10-01T00:00:00Z"}


def page(total: int) -> dict[str, object]:
    return {"page": 1, "per_page": 25, "total_count": total, "total_pages": 1}


def bodies() -> dict[str, object]:
    groceries: dict[str, object] = {"id": GROCERIES, "name": "Groceries", "color": "#00f", "icon": "carrot"}
    return {
        "/api/v1/accounts": {"accounts": [account(CHECKING, "Checking", "$1,234.56"),
                                          account("a2", "Visa", "$300.00", "liability")], "pagination": page(2)},
        "/api/v1/transactions": {"transactions": [transaction("Groceries run", "$12.34", "2026-10-30", groceries),
                                                  transaction("To savings", "$100.00", "2026-10-29",
                                                              transfer={"id": "x"})],
                                 "pagination": page(2)},
        "/api/v1/categories": {"categories": [
            {**groceries, "parent": {"id": "p1", "name": "Food"}, "subcategories_count": 0,
             "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z"}], "pagination": page(1)},
        "/api/v1/balance_sheet": {"currency": "USD",
                                  "net_worth": {"amount": "934.56", "currency": "USD", "formatted": "$934.56"},
                                  "assets": {"amount": "1234.56", "currency": "USD", "formatted": "$1,234.56"},
                                  "liabilities": {"amount": "300.0", "currency": "USD", "formatted": "$300.00"}},
    }


@dataclass
class FakeSure:
    """`status` answers every request with that status; `raw` with that body instead of JSON. `key` is the one key
    it accepts (401 otherwise)."""

    key: str = KEY
    status: int = 200
    raw: bytes | None = None
    answers: dict[str, object] = field(default_factory=bodies)
    seen: list[tuple[str, dict[str, str], str | None]] = field(default_factory=list[tuple[str, dict[str, str], str | None]])
    written: list[tuple[str, object]] = field(default_factory=list[tuple[str, object]])
    reads_only: bool = False
    split_parts: set[str] = field(default_factory=set[str])

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        self.seen.append((request.url.path, dict(request.url.params), request.headers.get("x-api-key")))
        if self.status != 200:
            return httpx2.Response(self.status, headers={"location": "https://elsewhere.test/"})
        if request.headers.get("x-api-key") != self.key:
            return httpx2.Response(401, json={"error": "unauthorized"})
        if self.raw is not None:
            return httpx2.Response(200, content=self.raw, headers={"content-type": "text/html"})
        if request.method == "PUT":
            return self._put(request)
        if request.url.path.startswith("/api/v1/categories/"):
            return self._category(request.url.path.rsplit("/", 1)[1])
        body = self.answers.get(request.url.path)
        if body is None:
            return httpx2.Response(404, json={"error": "not_found"})
        return httpx2.Response(200, content=json.dumps(body).encode(), headers={"content-type": "application/json"})

    def _rows(self, path: str, key: str) -> list[dict[str, Any]]:
        loose: Any = self.answers[path]
        return loose[key]

    def _category(self, id_: str) -> httpx2.Response:
        found = next((c for c in self._rows("/api/v1/categories", "categories") if c["id"] == id_), None)
        if found is None:
            return httpx2.Response(404, json={"error": "not_found", "message": "Category not found"})
        return httpx2.Response(200, json=found)

    def _put(self, request: httpx2.Request) -> httpx2.Response:
        """Sure's update: the transaction's category set to the body's `category_id`, the transaction answered."""
        if self.reads_only:
            return httpx2.Response(403, json={"error": "insufficient_scope",
                                              "message": "This action requires the 'write' scope"})
        id_ = request.url.path.removeprefix("/api/v1/transactions/")
        body = json.loads(request.content)
        self.written.append((request.url.path, body))
        found = next((t for t in self._rows("/api/v1/transactions", "transactions") if t["id"] == id_), None)
        if found is None:
            return httpx2.Response(404, json={"error": "not_found", "message": "Transaction not found"})
        if id_ in self.split_parts:
            return httpx2.Response(422, json={"error": "validation_failed", "message": "Split child transactions "
                                              "cannot be edited directly. Use the split editor."})
        category_id = body["transaction"]["category_id"]
        category = next(c for c in self._rows("/api/v1/categories", "categories") if c["id"] == category_id)
        found["category"] = {k: category[k] for k in ("id", "name", "color", "icon")}
        return httpx2.Response(200, json=found)

    def client(self) -> HttpSure:
        return HttpSure(httpx2.AsyncClient(transport=httpx2.MockTransport(self.handle), follow_redirects=False), 5)


def _slot(kind: Kind, person_id: int | None) -> str:
    return kind if person_id is None else f"{kind}:{person_id}"


@dataclass
class HeldConnections(Connections):
    """One household's connections in memory. `down` makes every call raise ConnectionsUnavailable."""

    held: dict[tuple[int, str], Opened] = field(default_factory=dict[tuple[int, str], Opened])
    down: bool = False
    answers: list[int] = field(default_factory=list[int])

    def can_open(self) -> bool:
        return True

    def connect(self, household_id: int, base: str = BASE, key: str = KEY, kind: Kind = "sure",
                person_id: int | None = None) -> None:
        connection = Connection(len(self.held) + 1, household_id, kind, base, 1, EPOCH, EPOCH, person_id)
        self.held[(household_id, _slot(kind, person_id))] = Opened(connection, key)

    def _up(self) -> None:
        if self.down:
            raise ConnectionsUnavailable("down")

    async def of_household(self, household_id: int, person_id: int | None = None) -> tuple[Connection, ...]:
        self._up()
        return tuple(o.connection for (h, _), o in self.held.items()
                     if h == household_id and o.connection.person_id in (None, person_id))

    async def opened(self, connection_id: int, household_id: int, person_id: int | None = None) -> Opened | None:
        self._up()
        return next((o for (h, _), o in self.held.items() if o.connection.id == connection_id and h == household_id
                     and o.connection.person_id in (None, person_id)), None)

    async def add(self, household_id: int, kind: Kind, label: str, base_url: str, secret: str,
                  added_by: int, holder: Holder | None = None) -> Connection:
        self._up()
        owner = added_by if services.get(ConnectionKinds).is_personal(kind) else None
        self.connect(household_id, base_url, secret, kind, owner)
        return self.held[(household_id, _slot(kind, owner))].connection

    async def replace(self, connection_id: int, household_id: int, person_id: int, base_url: str,
                      secret: str) -> Connection | None:
        raise NotImplementedError

    async def relabel(self, connection_id: int, household_id: int, person_id: int,
                      label: str) -> Connection | None:
        raise NotImplementedError

    async def seed(self, household_id: int, kind: Kind, base_url: str, secret: str) -> Connection | None:
        self._up()
        if (household_id, kind) in self.held:
            return None
        self.connect(household_id, base_url, secret, kind)
        return self.held[(household_id, kind)].connection

    async def remove(self, connection_id: int, household_id: int, person_id: int | None) -> bool:
        self._up()
        slot = next((k for k, o in self.held.items() if o.connection.id == connection_id and k[0] == household_id
                     and o.connection.person_id in (None, person_id)), None)
        return slot is not None and self.held.pop(slot, None) is not None

    async def answered(self, connection_id: int) -> None:
        self._up()
        self.answers.append(connection_id)


def params_of(seen: list[tuple[str, dict[str, str], str | None]], path: str) -> Mapping[str, str]:
    return next(q for p, q, _ in seen if p == path)
