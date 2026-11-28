"""Wire models for Find (`api.find`)."""

from datetime import date, datetime

from pydantic import BaseModel

from ..find.model import Kind


class FoundRecord(BaseModel):
    """One record a source found. `ref` is its id within its `kind`: a fact id (`memory`), a turn id (`conversation`,
    followed by `GET /api/chat/conversations/{within}`), a print library file id (`print`), a ledger transaction id
    (`transaction`). `within` is the ref of the record it sits in, null for none. `when` is when it was said or
    learned and `dated` the day a transaction is dated, each null when the source keeps no such time. `confirmed` is
    false for a guess."""

    kind: Kind
    ref: str
    title: str
    when: datetime | None
    dated: date | None
    confirmed: bool
    within: str | None


class FindResults(BaseModel):
    """What one search found: `found`, each source's records best first, sources in the order memory, conversation,
    print, transaction; `answered`, the sources that answered, with nothing too; `unreachable`, those that could not
    answer, whose records are missing, not absent. A source that is not connected is in neither list."""

    found: list[FoundRecord]
    answered: list[Kind]
    unreachable: list[Kind]
