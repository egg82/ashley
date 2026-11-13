"""The parts of Sure's JSON bodies she reads (we-promise/sure `app/views/api/v1/*/_*.json.jbuilder`,
`Api::V1::BalanceSheetController#show` and `Money#as_json` in `lib/money.rb`). Fields she does not read are ignored;
a field she reads that a Sure version leaves out is optional where she can do without it. `parsed` turns a body into
one of these or raises SureFailed (`not_sure`)."""

from typing import TypeVar

from pydantic import BaseModel, ValidationError

from .client import SureFailed


class Named(BaseModel):
    id: str
    name: str


class Account(BaseModel):
    id: str
    name: str
    balance: str | None = None
    balance_cents: int | None = None
    currency: str | None = None
    classification: str | None = None
    account_type: str | None = None
    status: str | None = None


class Transaction(BaseModel):
    id: str | None = None
    date: str
    name: str
    amount: str | None = None
    signed_amount_cents: int | None = None
    currency: str | None = None
    classification: str | None = None
    excluded: bool = False
    split_parent: bool = False
    account: Named | None = None
    category: Named | None = None
    merchant: Named | None = None
    transfer: object | None = None


class Category(BaseModel):
    id: str
    name: str
    parent: Named | None = None


class Pagination(BaseModel):
    total_count: int


class Accounts(BaseModel):
    accounts: list[Account]
    pagination: Pagination | None = None


class Transactions(BaseModel):
    transactions: list[Transaction]
    pagination: Pagination | None = None


class Categories(BaseModel):
    categories: list[Category]
    pagination: Pagination | None = None


class Money(BaseModel):
    """Sure's `Money#as_json`: `formatted` is the amount as Sure shows it, with its currency's sign."""

    formatted: str
    currency: str | None = None


class BalanceSheet(BaseModel):
    currency: str | None = None
    net_worth: Money
    assets: Money
    liabilities: Money


M = TypeVar("M", bound=BaseModel)


def parsed(model: type[M], body: object) -> M:
    """Raises SureFailed(`not_sure`) when `body` is not that shape."""
    try:
        return model.model_validate(body)
    except ValidationError as e:
        raise SureFailed("not_sure") from e
