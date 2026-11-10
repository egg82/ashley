"""Sure as the household's Ledger (`ashley.ledger.ledger`): its accounts, categories, balance sheet and transactions
read through the household's Sure connection and turned from `wire`'s shapes into the ledger's neutral records. Every
answered read moves the connection's `checked_at`. Nothing outside this module and `wire` knows Sure's field names."""

from collections.abc import Mapping

from pydantic import BaseModel

from .. import services
from ..connections import answered, ports
from ..connections.connections import Connections, ConnectionsUnavailable
from ..connections.model import Opened
from ..ledger.ledger import Ledger
from ..ledger.model import Account, Category, Entry, LedgerFailed, LedgerUnavailable, NetWorth, NotConnected, Page, Reason, TransactionQuery
from . import wire
from .client import Reason as SureReason, Sure, SureFailed

_REASON: dict[SureReason, Reason] = {"refused": "refused", "unreachable": "unreachable", "not_sure": "unrecognised"}


class SureLedger(Ledger):
    async def connected(self, household_id: int) -> bool:
        return await _opened(household_id) is not None

    async def accounts(self, household_id: int, limit: int) -> Page[Account]:
        got = await _read(household_id, "/api/v1/accounts", {"per_page": limit}, wire.Accounts)
        rows = tuple(Account(a.id, a.name, a.balance, a.account_type, a.classification) for a in got.accounts)
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
