"""Sure as the household's Ledger (`ashley.ledger.ledger`): its accounts, categories, balance sheet and transactions
read through the household's Sure connection and turned from `wire`'s shapes into the ledger's neutral records, and a
transaction's category set through it. Every answered call moves the connection's `checked_at`. Nothing outside this
module and `wire` knows Sure's field names. A categorisation logs `sure.categorised` with the connection id and counts."""

import logging
from collections.abc import Mapping, Sequence
from urllib.parse import quote

from pydantic import BaseModel

from .. import logs, services
from ..connections import answered, ports
from ..connections.connections import Connections, ConnectionsUnavailable
from ..connections.model import Opened
from ..ledger.ledger import Ledger
from ..ledger.model import (Account, Categorised, Category, Entry, LedgerFailed, LedgerUnavailable, NetWorth, NotConnected,
                            Page, Reason, Recurring, TransactionQuery, UnknownCategory)
from . import wire
from .client import Reason as SureReason, Sure, SureFailed

log = logging.getLogger("ashley.sure")
_REASON: dict[SureReason, Reason] = {"refused": "refused", "unreachable": "unreachable", "not_sure": "unrecognised",
                                     "not_found": "unrecognised", "rejected": "unrecognised"}
_ONE: dict[SureReason, Categorised] = {"not_found": "not_found", "rejected": "rejected"}


class SureLedger(Ledger):
    async def connected(self, household_id: int) -> bool:
        return await _opened(household_id) is not None

    async def accounts(self, household_id: int, limit: int) -> Page[Account]:
        got = await _read(household_id, "/api/v1/accounts", {"per_page": limit}, wire.Accounts)
        rows = tuple(Account(a.id, a.name, a.balance, a.account_type, a.classification, a.balance_cents) for a in got.accounts)
        return Page(rows, _total(got.pagination))

    async def categories(self, household_id: int, limit: int) -> Page[Category]:
        got = await _read(household_id, "/api/v1/categories", {"per_page": limit}, wire.Categories)
        rows = tuple(Category(c.id, c.name, c.parent.name if c.parent is not None else None) for c in got.categories)
        return Page(rows, _total(got.pagination))

    async def net_worth(self, household_id: int) -> NetWorth:
        got = await _read(household_id, "/api/v1/balance_sheet", {}, wire.BalanceSheet)
        return NetWorth(got.net_worth.formatted, got.assets.formatted, got.liabilities.formatted, got.currency)

    async def transactions(self, household_id: int, query: TransactionQuery) -> Page[Entry]:
        got = await _read(household_id, "/api/v1/transactions", _params(query), wire.Transactions)
        return Page(tuple(entry_from(t) for t in got.transactions), _total(got.pagination))

    async def recurring(self, household_id: int, limit: int) -> Page[Recurring]:
        got = await _read(household_id, "/api/v1/recurring_transactions", {"per_page": limit}, wire.RecurringTransactions)
        return Page(tuple(_recurring_from(r) for r in got.recurring_transactions), _total(got.pagination))

    async def categorise(self, household_id: int, category_id: str,
                         transaction_ids: Sequence[str]) -> Mapping[str, Categorised]:
        opened = await _opened(household_id)
        if opened is None:
            raise NotConnected
        base, key, sure = opened.connection.base_url, opened.secret, services.get(Sure)
        done: dict[str, Categorised] = {}
        try:
            try:
                wire.parsed(wire.Category, await sure.get(base, key, f"/api/v1/categories/{_segment(category_id)}", {}))
            except SureFailed as e:
                if e.reason == "not_found":
                    raise UnknownCategory from e
                raise
            for transaction_id in transaction_ids:
                done[transaction_id] = await _set(sure, base, key, transaction_id, category_id)
        except SureFailed as e:
            raise LedgerFailed(_REASON[e.reason]) from e
        finally:
            _counted(opened.connection.id, done)
        await answered.record(opened.connection.id)
        return done


def _params(query: TransactionQuery) -> dict[str, str | int]:
    """Sure's query for `query`: only what it sets."""
    named: dict[str, str | int | None] = {
        "start_date": query.start, "end_date": query.end, "account_id": query.account_id,
        "category_id": query.category_id, "search": query.search, "type": query.kind, "per_page": query.per_page,
        "page": query.page}
    return {k: v for k, v in named.items() if v is not None}


def entry_from(t: wire.Transaction) -> Entry:
    account, category, merchant = t.account, t.category, t.merchant
    return Entry(
        id=t.id, date=t.date, name=t.name, amount=t.amount,
        cents=abs(t.signed_amount_cents) if t.signed_amount_cents is not None else None,
        classification=t.classification, account_id=account.id if account else None,
        account=account.name if account else None, category=category.name if category else None,
        merchant=merchant.name if merchant else None, transfer=t.transfer is not None, excluded=t.excluded,
        split=t.split_parent)


def _recurring_from(r: wire.RecurringTransaction) -> Recurring:
    return Recurring(
        id=r.id, name=r.name, merchant=r.merchant.name if r.merchant else None,
        account_id=r.account.id if r.account else None, cents=int((abs(r.amount) * 100).to_integral_value()),
        due=r.next_expected_date, kind="income" if r.bill_type == "income" else "expense", autopay=r.autopay,
        ended=r.status == "inactive")


async def _set(sure: Sure, base: str, key: str, transaction_id: str, category_id: str) -> Categorised:
    """One transaction set to the category, or what Sure said of that transaction alone. Raises SureFailed otherwise."""
    try:
        body = await sure.put(base, key, f"/api/v1/transactions/{_segment(transaction_id)}",
                              {"transaction": {"category_id": category_id}})
    except SureFailed as e:
        if e.reason in _ONE:
            return _ONE[e.reason]
        raise
    wire.parsed(wire.Transaction, body)
    return "set"


def _segment(text: str) -> str:
    """`text` as one path segment, so an id cannot name another endpoint."""
    return quote(text, safe="")


def _counted(connection_id: int, done: Mapping[str, Categorised]) -> None:
    values = list(done.values())
    logs.info(log, "sure.categorised", connection=connection_id, set=values.count("set"),
              not_found=values.count("not_found"), rejected=values.count("rejected"))


def _total(pagination: wire.Pagination | None) -> int | None:
    return pagination.total_count if pagination is not None else None


async def _opened(household_id: int) -> Opened | None:
    try:
        return await ports.opened(services.get(Connections), "ledger", household_id)
    except ConnectionsUnavailable as e:
        raise LedgerUnavailable from e


async def _read[M: BaseModel](household_id: int, path: str, params: Mapping[str, str | int], model: type[M]) -> M:
    opened = await _opened(household_id)
    if opened is None:
        raise NotConnected
    try:
        body = await services.get(Sure).get(opened.connection.base_url, opened.secret, path, params)
        got = wire.parsed(model, body)
    except SureFailed as e:
        raise LedgerFailed(_REASON[e.reason]) from e
    await answered.record(opened.connection.id)
    return got
