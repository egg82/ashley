"""What she knows of the signed-in person, which they may see, correct and forget (`decisions.md`, "People see, correct
and forget what she knows of them"). The facts are `Memory.held`'s: about the person, theirs, or the household's,
under recall's visibility filter for them alone. A fact outside that set is 404 to every route here, whether or not it
exists, so nobody learns of a fact they may not see.

A correction is a short web conversation of its own, kind `command`, the person its participant, not remembered, its
one turn the text they typed; the old fact is superseded through `Memory.apply` with that conversation as the source.
A move between a person and the household is a correction that keeps the text and changes whose it is.
Forgetting deletes the fact and every version it replaced. Remembering a line of a conversation the person took part in
runs the write job's decision over it now (`ashley.memory.remember`); a conversation they were not in is 404, as one
that does not exist. Fact text is never logged."""

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Path
from fastapi.responses import JSONResponse

from .. import services
from ..conversations.conversations import Conversations, ConversationsUnavailable
from ..conversations.model import NewTurn
from ..memory.memory import Memory, MemoryUnavailable
from ..memory.remember import RememberRefused, RememberUnavailable, remember
from ..memory.model import Fact, Held, NewFact, Update, Visibility
from ..people.model import Person as PersonValue
from ..people.people import People, PeopleUnavailable
from .models import (CorrectionRequest, ErrorResponse, FactSource, ForgetResponse, MemoryFact, MemoryFactsResponse,
                     MoveRequest, Person as PersonModel, RememberRequest, RememberResponse, ReplacedFact,
                     wire_person)
from .person import Person

router = APIRouter()
_FactId = Annotated[int, Path(ge=1)]
_NOT_FOUND = "no such fact"
_DOWN = (MemoryUnavailable, PeopleUnavailable, ConversationsUnavailable)
_SIGNED_IN: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "`unauthorized`: no live session"},
    503: {"model": ErrorResponse, "description": "`unavailable`: memory or the database could not be reached"}}
_WRITE: dict[int | str, dict[str, Any]] = {
    **_SIGNED_IN,
    403: {"model": ErrorResponse, "description": "`forbidden`: the request came from another site or was not JSON"},
    404: {"model": ErrorResponse, "description": "`not_found`: no current fact of yours has that id"},
    422: {"model": ErrorResponse, "description": "a fact id below 1 or a body outside the request model gets "
          "FastAPI's own validation error, which is not this schema"}}


def _error(status: int, code: Literal["forbidden", "not_found", "refused", "unavailable"], detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content=ErrorResponse(code=code, detail=detail).model_dump())


def _unavailable() -> JSONResponse:
    return _error(503, "unavailable", "memory is unavailable right now; try again shortly")


async def _people(household_id: int) -> dict[int, PersonModel]:
    household = await services.get(People).household(household_id)
    people = household.people if household is not None else ()
    return {p.id: wire_person(p) for p in people}


def _wire(held: Held, people: dict[int, PersonModel]) -> MemoryFact:
    fact, replaced, source = held.fact, held.replaced, held.source
    return MemoryFact(
        id=fact.id, text=fact.text, kind=fact.kind, standing=fact.standing, visibility=fact.visibility,
        about=None if fact.about_id is None else people[fact.about_id],
        owner=None if fact.owner_id is None else people[fact.owner_id], valid_from=fact.valid_from,
        replaced=None if replaced is None else ReplacedFact(text=replaced.text, valid_to=replaced.valid_to),
        source=FactSource(conversation_id=source.conversation_id, conversation_kind=source.conversation_kind,
                          started_at=source.started_at, took_part=source.took_part, channel=source.channel, place=source.place))


@router.get("/api/memory/facts", response_model=MemoryFactsResponse, responses=_SIGNED_IN)
async def list_facts(signed_in: Person) -> MemoryFactsResponse | JSONResponse:
    """200 `MemoryFactsResponse`; 401 `unauthorized`; 503 `unavailable`."""
    person = signed_in.person
    try:
        held = await services.get(Memory).held(person.household_id, person.id)
        people = await _people(person.household_id)
    except _DOWN:
        return _unavailable()
    return MemoryFactsResponse(items=[_wire(h, people) for h in held])


@router.post("/api/memory/facts/{fact_id}/corrections", status_code=201, response_model=MemoryFact, responses={
    **_WRITE, 403: {"model": ErrorResponse, "description": "`forbidden`: from another site or not JSON, or a "
                    "`visibility` change by someone other than the fact's owner"}})
async def correct_fact(signed_in: Person, fact_id: _FactId, body: CorrectionRequest) -> MemoryFact | JSONResponse:
    """201 `MemoryFact`, the fact that replaces `fact_id`; 401 `unauthorized`; 403 `forbidden`; 404 `not_found`;
    422 FastAPI's validation error for a body outside `CorrectionRequest`; 503 `unavailable`."""
    person = signed_in.person
    try:
        found = await services.get(Memory).held(person.household_id, person.id, fact_id)
        if not found:
            return _error(404, "not_found", _NOT_FOUND)
        old = found[0]
        visibility = body.visibility or old.fact.visibility
        if visibility != old.fact.visibility and old.fact.owner_id != person.id:
            return _error(403, "forbidden", "only the fact's owner says who may know it")
        new_id = await _supersede(person, old, body.text, visibility, old.fact.about_id, old.fact.owner_id)
        now = () if new_id is None else await services.get(Memory).held(person.household_id, person.id, new_id)
        if not now:
            return _error(404, "not_found", _NOT_FOUND)
        people = await _people(person.household_id)
    except _DOWN:
        return _unavailable()
    return _wire(now[0], people)


async def _supersede(person: PersonValue, old: Held, text: str, visibility: Visibility, about_id: int | None,
                     owner_id: int | None) -> int | None:
    """The id of the fact that replaces `old`, written from a web conversation of its own; None when `old` stopped
    being current meanwhile."""
    fact = old.fact
    talk = await services.get(Conversations).start(person.household_id, "command", [person.id], remembered=False,
                                                           channel="web")
    turn = await services.get(Conversations).add_turn(talk.id, NewTurn("person", text, person.id, "private", person.id))
    new = NewFact(about_id, owner_id, visibility, True, fact.kind, fact.standing, text, turn.id)
    try:
        (new_id,) = await services.get(Memory).apply(person.household_id, talk.id, [Update(fact.id, new)], turn.at)
    except ValueError:
        return None
    return new_id


@router.post("/api/memory/facts/{fact_id}/moves", status_code=201, response_model=MemoryFact, responses={
    **_WRITE, 403: {"model": ErrorResponse, "description": "`forbidden`: from another site or not JSON, or a fact "
                    "that is about or owned by someone else, or already where it was asked to go"}})
async def move_fact(signed_in: Person, fact_id: _FactId, body: MoveRequest) -> MemoryFact | JSONResponse:
    """201 `MemoryFact`, the fact that replaces `fact_id`; 401 `unauthorized`; 403 `forbidden`; 404 `not_found`;
    422 FastAPI's validation error for a body outside `MoveRequest`; 503 `unavailable`."""
    person = signed_in.person
    try:
        found = await services.get(Memory).held(person.household_id, person.id, fact_id)
        if not found:
            return _error(404, "not_found", _NOT_FOUND)
        old = found[0]
        moved = _moved(old.fact, body.to, person.id)
        if moved is None:
            return _error(403, "forbidden", "only a fact of yours becomes the household's, and only a household "
                                            "fact becomes yours")
        new_id = await _supersede(person, old, old.fact.text, *moved)
        now = () if new_id is None else await services.get(Memory).held(person.household_id, person.id, new_id)
        if not now:
            return _error(404, "not_found", _NOT_FOUND)
        people = await _people(person.household_id)
    except _DOWN:
        return _unavailable()
    return _wire(now[0], people)


def _moved(fact: Fact, to: Literal["household", "mine"], person_id: int) -> tuple[Visibility, int | None, int | None] | None:
    """The visibility, about and owner `fact` takes when moved `to`, or None when this person may not move it so."""
    if to == "household":
        yours = fact.owner_id == person_id and fact.about_id is None
        return ("members" if fact.kind == "finance" else "shared", None, None) if yours else None
    if fact.owner_id is not None or fact.about_id is not None:
        return None
    return ("private" if fact.visibility == "members" else fact.visibility, None, person_id)


@router.delete("/api/memory/facts/{fact_id}", response_model=ForgetResponse, responses=_WRITE)
async def forget_fact(signed_in: Person, fact_id: _FactId) -> ForgetResponse | JSONResponse:
    """200 `ForgetResponse`; 401 `unauthorized`; 403 `forbidden`; 404 `not_found`; 503 `unavailable`."""
    person = signed_in.person
    memory = services.get(Memory)
    try:
        if not await memory.held(person.household_id, person.id, fact_id):
            return _error(404, "not_found", _NOT_FOUND)
        deleted = await memory.forget(person.household_id, fact_id, by=person.id)
    except ValueError:
        return _error(404, "not_found", _NOT_FOUND)
    except _DOWN:
        return _unavailable()
    return ForgetResponse(deleted=deleted)


@router.post("/api/memory/remembered", response_model=RememberResponse, responses={
    **_SIGNED_IN, 403: {"model": ErrorResponse, "description": "`forbidden`: the request came from another site or was "
                        "not JSON"},
    404: {"model": ErrorResponse, "description": "`not_found`: no turn of a conversation you took part in has that id"},
    422: {"model": ErrorResponse, "description": "`refused`: her model declined to decide over the line; a body outside "
          "`RememberRequest` gets FastAPI's own validation error instead, which is not this schema"}})
async def remember_turn(signed_in: Person, body: RememberRequest) -> RememberResponse | JSONResponse:
    """200 `RememberResponse`; 401 `unauthorized`; 403 `forbidden`; 404 `not_found`; 422 `refused`, or FastAPI's
    validation error for a body outside `RememberRequest`; 503 `unavailable`."""
    person = signed_in.person
    try:
        talk = await services.get(Conversations).get(body.conversation_id)
        if talk is None or person.id not in talk.participants or not any(t.id == body.turn_id for t in talk.turns):
            return _error(404, "not_found", "no such line")
        done = await remember(talk, body.turn_id)
        held = {h.fact.id: h for h in await services.get(Memory).held(person.household_id, person.id)}
        people = await _people(person.household_id)
    except RememberRefused:
        return _error(422, "refused", "she could not make anything of that line")
    except (RememberUnavailable, *_DOWN):
        return _unavailable()
    seen = [_wire(held[i], people) for i in done.inserted if i in held]
    return RememberResponse(facts=seen, unseen=len(done.inserted) - len(seen), ended=done.ended)
