"""Receipts in her history (`decisions.md`, "A turn that has read outside words asks..."): a turn of hers that had
`Turn.receipts` carries, on a line of its own after her words, what code showed beside them, and a person's agreeing
turn that had `Turn.agreed` carries what became of the calls it agreed to; each marked as the app's and not hers, so she
knows what the person saw and never takes it for something she said."""

from ..conversations.model import AgreedCall, AgreedOutcome, Receipt, Receipts, Turn
from ..tools import outside_config

_CONFIG = outside_config.load()
_STATUS = {"ran": _CONFIG.agreed_ran, "failed": _CONFIG.agreed_failed, "not_run": _CONFIG.not_run}


def line(receipts: Receipts) -> str:
    """The marked line for `receipts`: each change that ran by its headline, then each call waiting for the person's OK
    by its headline and code's summary of it, then each choice row shown by its label and value."""
    parts: list[str] = []
    if receipts.done:
        parts.append(_CONFIG.history_done.format(items="; ".join(r.headline for r in receipts.done)))
    if receipts.held:
        parts.append(_CONFIG.history_held.format(items="; ".join(_held(r) for r in receipts.held)))
    if receipts.facts:
        parts.append(_CONFIG.history_facts.format(items="; ".join(f"{f.label}: {f.value}" for f in receipts.facts)))
    return _CONFIG.history_line.format(receipts="  ".join(parts))


def agreed_line(outcome: AgreedOutcome) -> str:
    """The marked line for `outcome`: each agreed call by code's summary and what became of it, or that the run was
    interrupted."""
    if outcome.interrupted:
        return _CONFIG.history_agreed_interrupted
    return _CONFIG.history_agreed.format(items="; ".join(_agreed(c) for c in outcome.calls))


def after(turn: Turn) -> str:
    """The text a carried `turn` ends with: a newline and `line` for its receipts, a newline and `agreed_line` for its
    agreed outcome, nothing for a turn with neither."""
    receipts = "" if turn.receipts is None else f"\n{line(turn.receipts)}"
    return receipts + ("" if turn.agreed is None else f"\n{agreed_line(turn.agreed)}")


def _held(receipt: Receipt) -> str:
    return receipt.headline if receipt.detail is None else f"{receipt.headline} ({receipt.detail})"


def _agreed(call: AgreedCall) -> str:
    return f"{call.summary}: {_STATUS[call.status]}"
