"""What a money tool answers, made compact from the ledger's records (`ashley.ledger.model`): names, dates and amounts
as the backend formats them, ids only where another tool takes them, and `cut` true when the backend holds more than was
shown."""

from collections.abc import Mapping, Sequence

from ..ledger.model import Account, Categorised, Category, Entry, NetWorth, Page


def _cut(shown: int, total: int | None) -> bool:
    return total is not None and total > shown


def accounts(found: Page[Account]) -> dict[str, object]:
    rows = [{k: v for k, v in {"id": a.id, "name": a.name, "balance": a.balance, "type": a.type,
                               "classification": a.classification}.items() if v is not None}
            for a in found.rows]
    return {"accounts": rows, "cut": _cut(len(rows), found.total)}


def transaction(t: Entry) -> dict[str, object]:
    row: dict[str, object] = {"date": t.date, "name": t.name} if t.id is None else {"id": t.id, "date": t.date,
                                                                                   "name": t.name}
    if t.amount is not None:
        row["amount"] = t.amount
    if t.classification is not None:
        row["classification"] = t.classification
    for key, named in (("account", t.account), ("category", t.category), ("merchant", t.merchant)):
        if named is not None:
            row[key] = named
    if t.transfer:
        row["transfer"] = True
    if t.excluded:
        row["excluded"] = True
    if t.split:
        row["split"] = True
    return row


def transactions(found: Page[Entry]) -> dict[str, object]:
    rows = [transaction(t) for t in found.rows]
    out: dict[str, object] = {"transactions": rows, "cut": _cut(len(rows), found.total)}
    if found.total is not None:
        out["matched"] = found.total
    return out


def categories(found: Page[Category]) -> dict[str, object]:
    rows: list[dict[str, object]] = []
    for c in found.rows:
        row: dict[str, object] = {"id": c.id, "name": c.name}
        if c.parent is not None:
            row["parent"] = c.parent
        rows.append(row)
    return {"categories": rows, "cut": _cut(len(rows), found.total)}


def categorised(done: Mapping[str, Categorised]) -> dict[str, object]:
    """How many were set, and the ids of those that were not: `not_found`, no such transaction of the household;
    `rejected`, Sure would not change it."""
    out: dict[str, object] = {"set": sum(1 for v in done.values() if v == "set")}
    for outcome in ("not_found", "rejected"):
        ids = [i for i, v in done.items() if v == outcome]
        if ids:
            out[outcome] = ids
    return out


def recategorising(category: Category, entries: Sequence[Entry]) -> str:
    """The line the person agrees to before `entries` go to `category`: each by its date, amount and account and the
    category it leaves. Never a transaction's name or merchant, which are written outside the household."""
    to = category.name if category.parent is None else f"{category.parent} / {category.name}"
    each = [f"{e.date}, {e.amount or 'no amount'}{f' in {e.account}' if e.account else ''}, from "
            f"{e.category or 'no category'}" for e in entries]
    return f"Move {len(entries)} transaction{'' if len(entries) == 1 else 's'} to {to}: {'; '.join(each)}"


def net_worth(worth: NetWorth) -> dict[str, object]:
    out: dict[str, object] = {"net_worth": worth.net_worth, "assets": worth.assets, "liabilities": worth.liabilities}
    if worth.currency is not None:
        out["currency"] = worth.currency
    return out
