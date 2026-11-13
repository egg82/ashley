"""The household's money as she sees it, whatever app keeps it: plain records whose fields are stated in the ledger's
terms. An adapter (for Sure, `ashley.sure.ledger`) fills them from its backend's own shapes; nothing outside it knows
those shapes."""

from dataclasses import dataclass
from typing import Literal

Reason = Literal["refused", "unreachable", "unrecognised"]
"""Why a read failed: `refused`, the backend turned the household's key away; `unreachable`, no answer in time or a
server error; `unrecognised`, what answered is not that backend's API."""

Categorised = Literal["set", "not_found", "rejected"]
"""What became of one transaction `Ledger.categorise` was asked to change: `set`, it is in the category now; `not_found`,
the household has no such transaction; `rejected`, the backend would not change it (the part of a split, in Sure)."""

Kind = Literal["income", "expense"]
"""Which way money moved: `income` came in, `expense` went out."""


@dataclass(frozen=True)
class Account:
    """An account: `id` as `TransactionQuery.account_id` takes it, `name`, `balance` as the backend shows it (sign and
    currency included), `type` the backend's word for what sort of account it is, and `classification`
    (`asset` or `liability`). A field the backend leaves out is None."""

    id: str
    name: str
    balance: str | None
    type: str | None
    classification: str | None


@dataclass(frozen=True)
class Category:
    """A transaction category: `id` as `TransactionQuery.category_id` takes it, `name`, and its parent's name."""

    id: str
    name: str
    parent: str | None


@dataclass(frozen=True)
class NetWorth:
    """What the household owns and owes, each as the backend shows it, sign and currency included; `currency` is
    the code they are in, when the backend says."""

    net_worth: str
    assets: str
    liabilities: str
    currency: str | None


@dataclass(frozen=True)
class Entry:
    """One transaction as the ledger holds it. `id` is the backend's, None when it gives none; `date` the day it is
    dated, as the backend writes it (YYYY-MM-DD); `amount` as the backend shows it, sign and currency included;
    `cents` the size of the amount in minor units, unsigned; `classification` the backend's word for which way it moved
    (`income` or `expense` when it says so); `account_id` and the names of its `account`, `category` and `merchant`.
    `transfer` is true for money moved between the household's own accounts, `excluded` for a transaction the
    backend leaves out of its reports, `split` for the parent of a split. A field the backend leaves out is None."""

    id: str | None
    date: str
    name: str
    amount: str | None
    cents: int | None
    classification: str | None
    account_id: str | None
    account: str | None
    category: str | None
    merchant: str | None
    transfer: bool
    excluded: bool
    split: bool


@dataclass(frozen=True)
class TransactionQuery:
    """Which transactions, newest first: dated from `start` to `end` (YYYY-MM-DD, either may be None), in one account
    or category, whose name, notes or merchant hold `search`, going the way `kind` says; `per_page` of them, from the
    1-based `page` (None is the first)."""

    per_page: int
    start: str | None = None
    end: str | None = None
    account_id: str | None = None
    category_id: str | None = None
    search: str | None = None
    kind: Kind | None = None
    page: int | None = None


@dataclass(frozen=True)
class Page[T]:
    """What one read holds, and `total`, how many the backend holds in all (None when it does not say)."""

    rows: tuple[T, ...]
    total: int | None


class LedgerFailed(Exception):
    def __init__(self, reason: Reason) -> None:
        super().__init__(reason)
        self.reason: Reason = reason


class LedgerUnavailable(Exception):
    """The household's link to its ledger cannot be read."""


class UnknownCategory(Exception):
    """The category asked for is not one of the household's."""


class NotConnected(Exception):
    """The household has no ledger."""
