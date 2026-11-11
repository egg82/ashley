"""The household's pronunciation words (`decisions.md`, "Spoken words differ from written ones"). Any person of the
household reads and edits them from a signed-in session of this site; the household is always the session's, so no
route names or reaches another's.

`GET /api/lexicon` lists the words; `PUT /api/lexicon/{real}` sets one (200 with the word as stored, a new word or a
replaced spelling alike); `DELETE /api/lexicon/{real}` removes one, 404 when the household has no such word. A word or
spelling `LexiconRefused` names is 422 and nothing is stored. A word reaches speech on her next spoken reply.

One log line per edit (the store's `lexicon.changed`: ids and a count, never a word) and one per refusal."""

import logging
from typing import Any, Literal

from fastapi import APIRouter
from fastapi.responses import JSONResponse, Response

from .. import logs, services
from ..channels.lexicon import Refusal, refusal
from ..channels.lexicons import MAX_ENTRIES, Entry, LexiconFull, Lexicons, LexiconUnavailable
from ..people.people import People, PeopleUnavailable
from ..text import NoNul
from .lexicon_models import LexiconRefused, LexiconWord, LexiconWordRequest, LexiconWords
from .models import ErrorResponse, wire_person
from .person import Person

router = APIRouter()
log = logging.getLogger("ashley.api")
_READ: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "`unauthorized`: no live session"},
    503: {"model": ErrorResponse, "description": "`unavailable`: the database could not be reached"}}
_WRITE: dict[int | str, dict[str, Any]] = {
    **_READ, 403: {"model": ErrorResponse, "description": "`forbidden`: the request came from another site"},
    422: {"model": LexiconRefused, "description": "the word or its spelling is not one she can store; nothing was "
          "stored. A body outside the request's schema gets FastAPI's own validation error, which is not this schema"}}
_DELETE: dict[int | str, dict[str, Any]] = {
    **_WRITE, 404: {"model": ErrorResponse, "description": "`not_found`: the household has no such word"}}


def _unavailable() -> JSONResponse:
    return JSONResponse(status_code=503, content=ErrorResponse(
        code="unavailable", detail="the words are unavailable right now; try again shortly").model_dump())


async def _words(household_id: int, entries: tuple[Entry, ...]) -> list[LexiconWord]:
    found = await services.get(People).household(household_id)
    named = {p.id: wire_person(p) for p in (found.people if found is not None else ())}
    return [LexiconWord(real=e.real, spoken=e.spoken, updated_at=e.updated_at,
                        edited_by=None if e.updated_by is None else named.get(e.updated_by)) for e in entries]


def _refused(person: Person, reason: Refusal | Literal["full"]) -> JSONResponse:
    logs.info(log, "lexicon.refused", household=person.person.household_id, person=person.person.id, reason=reason)
    return JSONResponse(status_code=422, content=LexiconRefused(
        refused_for=reason, detail="that is not a word she can store").model_dump())


@router.get("/api/lexicon", response_model=LexiconWords, responses=_READ)
async def read_lexicon(signed_in: Person) -> LexiconWords | JSONResponse:
    """200 `LexiconWords`; 401 `unauthorized`; 503 `unavailable`."""
    household = signed_in.person.household_id
    try:
        entries = await services.get(Lexicons).entries(household)
        return LexiconWords(words=await _words(household, entries), limit=MAX_ENTRIES)
    except (LexiconUnavailable, PeopleUnavailable):
        return _unavailable()


@router.put("/api/lexicon/{real}", response_model=LexiconWord, responses=_WRITE)
async def put_word(signed_in: Person, real: NoNul, body: LexiconWordRequest) -> LexiconWord | JSONResponse:
    """200 `LexiconWord` as stored; 401 `unauthorized`; 403 `forbidden`; 422 `LexiconRefused`; 503 `unavailable`."""
    person = signed_in.person
    why = refusal(real, body.spoken)
    if why is not None:
        return _refused(signed_in, why)
    try:
        saved = await services.get(Lexicons).put(person.household_id, person.id, real, body.spoken)
        return (await _words(person.household_id, (saved,)))[0]
    except LexiconFull:
        return _refused(signed_in, "full")
    except (LexiconUnavailable, PeopleUnavailable):
        return _unavailable()


@router.delete("/api/lexicon/{real}", status_code=204, response_class=Response, responses=_DELETE)
async def delete_word(signed_in: Person, real: NoNul) -> Response:
    """204, removed; 401 `unauthorized`; 403 `forbidden`; 404 `not_found`; 503 `unavailable`."""
    person = signed_in.person
    try:
        removed = await services.get(Lexicons).remove(person.household_id, person.id, real)
    except LexiconUnavailable:
        return _unavailable()
    if not removed:
        return JSONResponse(status_code=404, content=ErrorResponse(
            code="not_found", detail="the household has no such word").model_dump())
    return Response(status_code=204)
