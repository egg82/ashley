"""A signed-in person searches everything she keeps in one go (`GET /api/find`): facts, their own conversations, the
print library and, since they read alone, the ledger. Each source applies its own access rule (`ashley.find.sources`);
the records come back at once, with no model call. Logs ids and counts, never the query."""

from typing import Annotated, Any

from fastapi import APIRouter, Query

from ..conversations.model import Hearer
from ..find.find import find as find_records
from ..find.model import Findings
from ..find.sources import everyday
from .find_models import FindResults, FoundRecord
from .models import ErrorResponse
from .person import Person

router = APIRouter()

_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "`unauthorized`: no live session"},
    422: {"model": ErrorResponse, "description": "a missing or empty `q`, or a `limit` outside 1 to 50, gets FastAPI's "
          "own validation error, which is not this schema"}}


@router.get("/api/find", response_model=FindResults, responses=_RESPONSES)
async def find(signed_in: Person, q: Annotated[str, Query(min_length=1, max_length=200)],
               limit: Annotated[int, Query(ge=1, le=50)] = 20) -> FindResults:
    """200 `FindResults`: up to `limit` records matching `q` from each source. A source that fails or times out is in
    `unreachable` and the others still answer; never 503. 401 `unauthorized`; 422 for a bad `q` or `limit`."""
    who = signed_in.person
    # A person's own session reaches them alone, as their web chat does for `ashley.channels.audience.owner_alone`.
    hearer = Hearer(who.household_id, who.id, owner_only=True)
    return _wire(await find_records(everyday(), hearer, q, limit))


def _wire(findings: Findings) -> FindResults:
    return FindResults(found=[FoundRecord(kind=f.kind, ref=f.ref, title=f.title, when=f.when, dated=f.dated,
                                          confirmed=f.confirmed, within=f.within) for f in findings.found],
                       answered=list(findings.answered), unreachable=list(findings.unreachable))
