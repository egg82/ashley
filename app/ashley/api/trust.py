"""What a person lets her just do (`decisions.md`, "What she may just do is a person's setting over the floor"). A
signed-in person reads and writes their own rows only, from a session of this site: nothing else reaches `TrustWriter`,
so no tool, channel or model call changes it.

`GET /api/trust` answers each kind with its label, the value in force and, where the code always offers it first,
`locked` and why. `PUT /api/trust` replaces the person's whole choice and must carry the revision read, else 409
`version_conflict`; a kind that is not one, or `act` on a locked kind, is 422 `TrustRefused` and nothing is stored.

One log line per write (the writer's `trust.changed`) and one per refusal (`trust.refused`: household, person, reason)."""

import logging
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from .. import logs, services
from ..trust.kinds import Kinds, TrustRefused as Refused, load
from ..trust.trust import StoredTrust, Trust, TrustUnavailable
from ..trust.trust_write import TrustWriter, VersionConflict
from .models import ErrorResponse
from .person import Person
from .trust_models import TrustRefused, TrustRequest, TrustRow, TrustSettings

router = APIRouter()
log = logging.getLogger("ashley.api")
KINDS: Kinds = load()
_READ: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "`unauthorized`: no live session"},
    503: {"model": ErrorResponse, "description": "`unavailable`: the choices could not be read or written"}}
_WRITE: dict[int | str, dict[str, Any]] = {
    **_READ, 403: {"model": ErrorResponse, "description": "`forbidden`: the request came from another site"},
    409: {"model": ErrorResponse, "description": "`version_conflict`: the choices changed since the revision sent"},
    422: {"model": TrustRefused, "description": "a kind that is not one, or `act` on a locked kind; nothing was "
          "stored. A body outside the request's schema gets FastAPI's own validation error, which is not this schema"}}


def _unavailable() -> JSONResponse:
    return JSONResponse(status_code=503, content=ErrorResponse(
        code="unavailable", detail="these choices are unavailable right now; try again shortly").model_dump())


def _wire(stored: StoredTrust) -> TrustSettings:
    values = KINDS.effective(stored.values)
    return TrustSettings(revision=stored.version, updated_at=stored.updated_at,
                         rows=[TrustRow(kind=k.kind, label=k.label, value=values[k.kind], locked=k.floor)
                               for k in KINDS.kinds])


@router.get("/api/trust", response_model=TrustSettings, responses=_READ)
async def read_trust(signed_in: Person) -> TrustSettings | JSONResponse:
    """200 `TrustSettings`; 401 `unauthorized`; 503 `unavailable`."""
    me = signed_in.person
    try:
        return _wire(await services.get(Trust).stored(me.household_id, me.id))
    except TrustUnavailable:
        return _unavailable()


@router.put("/api/trust", response_model=TrustSettings, responses=_WRITE)
async def write_trust(signed_in: Person, body: TrustRequest) -> TrustSettings | JSONResponse:
    """200 `TrustSettings` as stored; 401 `unauthorized`; 403 `forbidden`; 409 `version_conflict`; 422
    `TrustRefused`; 503 `unavailable`."""
    me = signed_in.person
    try:
        stored = await services.get(TrustWriter).put(me.household_id, me.id, body.revision,
                                                     {c.kind: c.value for c in body.picks})
    except Refused as e:
        logs.info(log, "trust.refused", household=me.household_id, person=me.id, reason=e.reason)
        return JSONResponse(status_code=422, content=TrustRefused(
            kind=e.kind, reason=e.reason, detail="that is not a choice this setting takes").model_dump())
    except VersionConflict:
        logs.info(log, "trust.refused", household=me.household_id, person=me.id, reason="version_conflict")
        return JSONResponse(status_code=409, content=ErrorResponse(
            code="version_conflict", detail="these choices changed since you opened them; reload and try again").model_dump())
    except TrustUnavailable:
        return _unavailable()
    return _wire(stored)
