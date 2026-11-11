"""The people of the signed-in person's household, and who of them is an admin (`decisions.md`, "An admin changes what
the deployment shares"). The household is always the session's, so no route names or reaches another's people.

`GET /api/people` lists them, for any person of the household. `PUT /api/people/{person_id}/admin` grants or revokes
admin, for an admin only (403 `admin_only` for anyone else); revoking the last admin is 409 `last_admin` and nothing
changes. A person of another household is 404, as one that does not exist. Only these routes, sign-in and the wiring
reach `Admins`.

One log line per change (the writer's `people.admin_granted` or `people.admin_revoked`, with both person ids) and one
per refusal."""

import logging
from typing import Any, Literal

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from .. import logs, services
from ..people.admins import Admins
from ..people.people import People, PeopleUnavailable
from .admin_gate import ADMIN_ONLY, Admin
from .models import ErrorResponse
from .people_models import AdminRequest, PeopleResponse, Person as WirePerson, wire_person
from .person import Person

router = APIRouter()
log = logging.getLogger("ashley.api")
_READ: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "`unauthorized`: no live session"},
    503: {"model": ErrorResponse, "description": "`unavailable`: the database could not be reached"}}
_WRITE: dict[int | str, dict[str, Any]] = {
    **_READ, **ADMIN_ONLY,
    404: {"model": ErrorResponse, "description": "`not_found`: no person of the signed-in person's household has that id"},
    409: {"model": ErrorResponse, "description": "`last_admin`: they are the deployment's last admin; nothing changed"},
    422: {"model": ErrorResponse, "description": "a body or id outside the request's schema gets FastAPI's own "
          "validation error, which is not this schema"}}


def _error(status: int, code: Literal["not_found", "unavailable", "last_admin"], detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content=ErrorResponse(code=code, detail=detail).model_dump())


def _unavailable() -> JSONResponse:
    return _error(503, "unavailable", "people are unavailable right now; try again shortly")


async def _people(household_id: int) -> list[WirePerson] | None:
    found = await services.get(People).household(household_id)
    return None if found is None else [wire_person(p) for p in found.people]


@router.get("/api/people", response_model=PeopleResponse, responses=_READ)
async def list_people(signed_in: Person) -> PeopleResponse | JSONResponse:
    """200 `PeopleResponse`; 401 `unauthorized`; 503 `unavailable`."""
    try:
        people = await _people(signed_in.person.household_id)
    except PeopleUnavailable:
        return _unavailable()
    return PeopleResponse(people=people or [])


@router.put("/api/people/{person_id}/admin", response_model=WirePerson, responses=_WRITE)
async def put_admin(signed_in: Admin, person_id: int, body: AdminRequest) -> WirePerson | JSONResponse:
    """200 `Person`, as they are now; 401 `unauthorized`; 403 `admin_only` or `forbidden`; 404 `not_found`; 409
    `last_admin`; 503 `unavailable`."""
    me = signed_in.person
    try:
        outcome = await services.get(Admins).put(me.household_id, person_id, body.admin, me.id)
        people = await _people(me.household_id) if outcome == "set" else None
    except PeopleUnavailable:
        return _unavailable()
    if outcome == "last_admin":
        logs.info(log, "people.admin_refused", person=person_id, by=me.id, reason=outcome)
        return _error(409, "last_admin", "the deployment needs at least one admin")
    changed = next((p for p in people or [] if p.id == person_id), None)
    return _error(404, "not_found", "there is no such person") if changed is None else changed
