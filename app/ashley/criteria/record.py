"""The record criteria are judged over, whatever backend it came from: a money transaction as plain fields. An adapter
(for the deposit sense, `ashley.senses.ledger_transactions`, from the Ledger's entries) makes it; nothing here or in
`predicates` knows a backend. `Change` is the other record: one watched item's change."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Literal, get_args

Direction = Literal["in", "out"]
DIRECTIONS: tuple[Direction, ...] = get_args(Direction)


@dataclass(frozen=True)
class Transaction:
    """One transaction reduced to what a criterion reads: `id`, the day it is dated, the account it is in,
    `cents` unsigned, whether its backend classes it income (`direction` in) or expense (out) and not a transfer, split parent
    or excluded (`counts`), and the names it carries (merchant, then its own name)."""

    id: str
    day: date
    account_id: str
    cents: int
    counts: bool
    names: tuple[str, ...]
    direction: Direction = "in"


Scalar = str | int | float | bool | None
Fields = Mapping[str, Scalar]
ChangeKind = Literal["new", "changed", "gone"]
CHANGE_KINDS: tuple[ChangeKind, ...] = get_args(ChangeKind)


def same(a: Scalar, b: Scalar) -> bool:
    """Whether two tracked values are the same: numbers compare by value, a boolean is never a number."""
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    return a == b


@dataclass(frozen=True)
class Change:
    """One item that is new, changed or gone between two reads of a watch: its `id`, which `kind` of change, and its
    tracked fields `before` (None when new) and `after` (None when gone). A changed item has both, and they differ."""

    id: str
    kind: ChangeKind
    before: Fields | None
    after: Fields | None

    def __post_init__(self) -> None:
        if self.kind not in CHANGE_KINDS:
            raise ValueError(f"a change is one of {', '.join(CHANGE_KINDS)}")
        if (self.before is None) != (self.kind == "new") or (self.after is None) != (self.kind == "gone"):
            raise ValueError("a new item has no before, a gone item no after, a changed item both")
        if self.kind == "changed" and self.before is not None and self.after is not None and not differs(
                self.before, self.after):
            raise ValueError("a changed item's fields differ")


def differs(before: Fields, after: Fields) -> bool:
    return before.keys() != after.keys() or any(not same(before[k], after[k]) for k in before)
