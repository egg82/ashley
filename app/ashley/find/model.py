"""What Find returns, as values."""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

Kind = Literal["memory", "conversation", "print", "transaction"]
"""Which system a record lives in: a fact she knows, a turn of a conversation, a file in the print library, a ledger
transaction."""


@dataclass(frozen=True)
class Found:
    """One record a source returned. `ref` is its id within its kind (a fact, turn, print file or transaction id) and
    `within` the ref of the record it sits in (a turn's conversation id), None when it sits in nothing. `title` is its
    text as the source keeps it; `when` the moment it was said or learned, and `dated` the day a record kept by
    day alone is dated (a transaction), each None when the source keeps no such time. `confirmed` comes from the
    record's own fields, False for a guess."""

    kind: Kind
    ref: str
    title: str
    when: datetime | None
    confirmed: bool
    within: str | None = None
    dated: date | None = None


@dataclass(frozen=True)
class Findings:
    """What every source made of one search: `found`, each source's records in its own best-first order, sources in
    the order they were given; `answered`, the sources that answered (with nothing, too); `unreachable`, those that
    failed or ran out of time. A source that does not serve this hearer, or that the household has not connected, is
    in neither."""

    found: tuple[Found, ...]
    answered: tuple[Kind, ...]
    unreachable: tuple[Kind, ...]


class SourceDown(Exception):
    """A source could not answer just now; Find names it in `unreachable`."""
