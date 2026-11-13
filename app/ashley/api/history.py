"""A signed-in person reads back their earlier conversations on any channel (`decisions.md`, "A person reads back their
earlier conversations"). They are the ones the person took part in; another's, and one that does not exist, are both 404.
A turn said privately to another participant (a reply sent to their phone in a shared room) is not shown to the rest.
Read only: nothing here posts into a conversation, closed or not. Logs ids and counts, never turns."""

import logging
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Path, Query
from fastapi.responses import JSONResponse

from .. import logs, services
from ..conversations.conversations import Conversations, ConversationsUnavailable
from ..channels import unprompted
from ..conversations.model import Conversation, Cursor, Summary, Turn
from ..people.model import Household
from ..people.model import Person as PersonRecord
from ..people.people import People, PeopleUnavailable
from .chat import wire_attachment
from .history_models import PastConversation, PastHistory, PastSummary, PastTurn
from .models import ErrorResponse
from .person import Person

log = logging.getLogger("ashley.api")
router = APIRouter()

_STAMP = "%Y%m%dT%H%M%S%f"
_SIGNED_IN: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "`unauthorized`: no live session"},
    503: {"model": ErrorResponse, "description": "`unavailable`: the database could not be reached"}}
_LIST: dict[int | str, dict[str, Any]] = {
    **_SIGNED_IN, 422: {"model": ErrorResponse, "description": "`refused`: `before` is not one a page returned; a "
                        "`limit` outside 1 to 50 gets FastAPI's own validation error, which is not this schema"}}
_ONE: dict[int | str, dict[str, Any]] = {
    **_SIGNED_IN, 404: {"model": ErrorResponse, "description": "`not_found`: no conversation of yours has that id"},
    422: {"model": ErrorResponse, "description": "an id below 1 gets FastAPI's own validation error, which is not "
          "this schema"}}


def cursor_text(cursor: Cursor) -> str:
    return f"{cursor.last_activity_at.astimezone(UTC).strftime(_STAMP)}-{cursor.id}"


def parse_cursor(text: str) -> Cursor | None:
    """The cursor `cursor_text` wrote, None for anything else."""
    stamp, dash, ident = text.partition("-")
    try:
        at = datetime.strptime(stamp, _STAMP).replace(tzinfo=UTC)
        return Cursor(at, int(ident)) if dash and ident.isdigit() else None
    except ValueError:
        return None


def _error(status: int, code: Literal["not_found", "refused", "unavailable"], detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content=ErrorResponse(code=code, detail=detail).model_dump())


def _unavailable() -> JSONResponse:
    return _error(503, "unavailable", "conversations are unavailable right now; try again shortly")


def _summary(found: Summary) -> PastSummary:
    return PastSummary(id=found.id, kind=found.kind, state=found.state, started_at=found.started_at,
                       last_activity_at=found.last_activity_at, channel=found.channel, place=found.place,
                       turn_count=found.turns)


@router.get("/api/chat/conversations", response_model=PastHistory, responses=_LIST)
async def history(signed_in: Person, limit: Annotated[int, Query(ge=1, le=50)] = 10,
                  before: Annotated[str | None, Query(max_length=64)] = None) -> PastHistory | JSONResponse:
    """200 `PastHistory`, the conversations the person took part in, newest activity first, `limit` at a time from
    `before` (a `next` a page returned); 401 `unauthorized`; 422 `refused` for a `before` no page returned; 503
    `unavailable`."""
    return await history_page(signed_in.person, limit, before, None)


async def history_page(who: PersonRecord, limit: int, before: str | None, thread: str | None) -> PastHistory | JSONResponse:
    """The page `history` answers, of the conversations that started on `thread` when it is given. Whoever calls with a
    `thread` has already decided the person may read it; the page is still only conversations they took part in."""
    after = None if before is None else parse_cursor(before)
    if before is not None and after is None:
        return _error(422, "refused", "that is not a place in the history")
    try:
        page = await services.get(Conversations).of_person(who.household_id, who.id, limit, after, thread)
    except ConversationsUnavailable:
        return _unavailable()
    logs.info(log, "chat.history", person=who.id, count=len(page.items), more=page.next is not None)
    return PastHistory(conversations=[_summary(s) for s in page.items],
                       next=None if page.next is None else cursor_text(page.next))


@router.get("/api/chat/conversations/{conversation_id}", response_model=PastConversation, responses=_ONE)
async def past(signed_in: Person, conversation_id: Annotated[int, Path(ge=1)]) -> PastConversation | JSONResponse:
    """200 `PastConversation`; 401 `unauthorized`; 404 `not_found` when the person did not take part, as when it does
    not exist; 503 `unavailable`."""
    who = signed_in.person
    try:
        found = await services.get(Conversations).get(conversation_id)
        if found is None or found.household_id != who.household_id or who.id not in found.participants:
            return _error(404, "not_found", "no such conversation")
        household = await services.get(People).household(who.household_id)
    except (ConversationsUnavailable, PeopleUnavailable):
        return _unavailable()
    wired = _wire(found, household, who)
    logs.info(log, "chat.past", person=who.id, conversation=found.id, turns=wired.turn_count,
              withheld=sum(not _heard_by(t, who) for t in found.turns))
    return wired


def _heard_by(turn: Turn, who: PersonRecord) -> bool:
    """Every turn of a conversation `who` took part in, except one said privately to another person (its owner)."""
    return turn.heard != "private" or turn.owner_id is None or turn.owner_id == who.id


def _wire(found: Conversation, household: Household | None, who: PersonRecord) -> PastConversation:
    names = {} if household is None else {p.id: p.name for p in household.people}
    turns = [PastTurn(id=t.id, author=t.author, text=t.text, at=t.at, follows=t.follows,
                      continued_on=t.continued_on, attachment=wire_attachment(t.attachment),
                      speaker=_speaker(t, names, household))
             for t in unprompted.shown(tuple(t for t in found.turns if _heard_by(t, who)))]
    return PastConversation(id=found.id, kind=found.kind, state=found.state, started_at=found.started_at,
                            last_activity_at=found.last_activity_at, channel=found.channel, place=found.place,
                            turn_count=len(turns), lines=turns)


def _speaker(turn: Turn, names: dict[int, str], household: Household | None) -> str | None:
    if turn.author == "household":
        return None if household is None else household.name
    return None if turn.speaker_id is None else names.get(turn.speaker_id)
