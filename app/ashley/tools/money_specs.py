"""The money tools as the model sees them, and their arguments checked into a ledger query. Every one only reads
(`ToolSpec.reads`)."""

import re
from datetime import date

from ..inference.model import ToolSpec
from ..ledger.model import TransactionQuery
from .money_config import MoneyConfig

ACCOUNTS = "money_accounts"
TRANSACTIONS = "money_transactions"
CATEGORIES = "money_categories"
NET_WORTH = "money_net_worth"
NAMES = (ACCOUNTS, TRANSACTIONS, CATEGORIES, NET_WORTH)

_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_NO_ARGS: dict[str, object] = {"type": "object", "properties": {}}

INSTRUCTIONS = ("The money tools read the household's finances in Sure, the app they keep them in: accounts with "
                "their balances, transactions, categories and net worth. They only read; you cannot change anything "
                "there. Amounts are as Sure shows them, sign and currency included. Filter transactions by the ids "
                "money_accounts and money_categories give, and say so when an answer was cut short.")


def specs(config: MoneyConfig) -> tuple[ToolSpec, ...]:
    transactions = {"type": "object", "properties": {
        "start_date": {"type": "string", "description": "first day, YYYY-MM-DD"},
        "end_date": {"type": "string", "description": "last day, YYYY-MM-DD"},
        "account_id": {"type": "string", "description": "one account, by the id money_accounts gives"},
        "category_id": {"type": "string", "description": "one category, by the id money_categories gives"},
        "search": {"type": "string", "description": "words in the name, notes or merchant"},
        "type": {"type": "string", "enum": ["income", "expense"]},
        "limit": {"type": "integer", "minimum": 1, "maximum": config.transactions_max,
                  "description": f"how many, newest first; {config.transactions_default} unless given"}}}
    return (
        ToolSpec(ACCOUNTS, "The household's accounts in Sure with their balances, type and id.", _NO_ARGS, reads=True, outside=False),
        ToolSpec(TRANSACTIONS, "The household's transactions in Sure, newest first, with date, name, amount, "
                 "account, category and merchant; how many matched, and whether the list was cut.", transactions,
                 reads=True, outside=True),
        ToolSpec(CATEGORIES, "The household's transaction categories in Sure, with id and parent.", _NO_ARGS,
                 reads=True, outside=False),
        ToolSpec(NET_WORTH, "The household's net worth in Sure: total assets, total liabilities and the difference.",
                 _NO_ARGS, reads=True, outside=False),
    )


def transaction_query(arguments: dict[str, object], config: MoneyConfig) -> TransactionQuery | str:
    """The ledger query for `money_transactions`'s arguments, or the reason they are wrong, which names no value."""
    given: dict[str, str] = {}
    for key in ("start_date", "end_date"):
        value = arguments.get(key)
        if value is None:
            continue
        if not isinstance(value, str) or not _is_date(value):
            return f"{key} is a date, YYYY-MM-DD"
        given[key] = value
    for key in ("account_id", "category_id"):
        value = arguments.get(key)
        if value is None:
            continue
        if not isinstance(value, str) or not _UUID.match(value):
            return f"{key} is an id as the money tools give it"
        given[key] = value
    search, kind, limit = arguments.get("search"), arguments.get("type"), arguments.get("limit")
    if search is not None:
        if not isinstance(search, str) or not search.strip() or len(search) > config.search_chars:
            return f"search is some words, at most {config.search_chars} characters"
        search = search.strip()
    if kind is not None and kind not in ("income", "expense"):
        return "type is income or expense"
    if limit is None:
        limit = config.transactions_default
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= config.transactions_max:
        return f"limit is a whole number from 1 to {config.transactions_max}"
    return TransactionQuery(
        per_page=limit, start=given.get("start_date"), end=given.get("end_date"), account_id=given.get("account_id"),
        category_id=given.get("category_id"), search=search,
        kind=None if kind is None else "income" if kind == "income" else "expense")


def _is_date(text: str) -> bool:
    try:
        date.fromisoformat(text)
    except ValueError:
        return False
    return len(text) == 10
