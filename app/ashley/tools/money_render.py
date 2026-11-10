"""What a money tool answers, made compact from the ledger's records (`ashley.ledger.model`): names, dates and amounts
as the backend formats them, ids only where another tool takes them, and `cut` true when the backend holds more than was
shown."""

from ..ledger.model import Account, Category, Entry, NetWorth, Page


def _cut(shown: int, total: int | None) -> bool:
    return total is not None and total > shown


def accounts(found: Page[Account]) -> dict[str, object]:
    rows = [{k: v for k, v in {"id": a.id, "name": a.name, "balance": a.balance, "type": a.type,
                               "classification": a.classification}.items() if v is not None}
            for a in found.rows]
    return {"accounts": rows, "cut": _cut(len(rows), found.total)}


def transaction(t: Entry) -> dict[str, object]:
    row: dict[str, object] = {"date": t.date, "name": t.name}
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


def net_worth(worth: NetWorth) -> dict[str, object]:
    out: dict[str, object] = {"net_worth": worth.net_worth, "assets": worth.assets, "liabilities": worth.liabilities}
    if worth.currency is not None:
        out["currency"] = worth.currency
    return out
