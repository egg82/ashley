"""Receipts flattened to text, for suites that assert on what code showed beside her reply."""

from ashley.conversations.model import Receipt, Receipts


def held_text(receipts: Receipts | None) -> str:
    """Each held call's headline, summary and why on lines of its own; empty when nothing is held."""
    return "" if receipts is None else "\n".join(_flat(r) for r in receipts.held)


def done_text(receipts: Receipts | None) -> str:
    """Each change that ran, as `held_text` gives a held one; empty when none ran."""
    return "" if receipts is None else "\n".join(_flat(r) for r in receipts.done)


def shown(receipts: Receipts | None) -> str:
    """Everything shown beside her reply: what ran, then what waits."""
    return "\n".join(t for t in (done_text(receipts), held_text(receipts)) if t)


def _flat(receipt: Receipt) -> str:
    return " | ".join(p for p in (receipt.headline, receipt.detail, receipt.why) if p)
