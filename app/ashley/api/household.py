"""The household page: a signed-in person reads and sets their own household's timezone, profile, locale, unit system,
clock and location. The household is always the session's, so no route names or reaches another's. Only this route
and the wiring reach `HouseholdWriter`, so nothing she does on her own sets them (a boundary test holds that).

`GET /api/household` answers the household; `PUT /api/household` replaces every field and answers it as stored. A
timezone, locale or location she cannot use is 422 `HouseholdRefused` and nothing is stored. A change reaches her from
her next reply.

`GET /api/household/quiet` and `PUT /api/household/quiet` read and replace the signed-in person's own quiet hours (never
another person's): a window that is not whole hours, or in a zone she cannot use, is 422 `QuietRefused`.

One log line per write (the writer's `people.household.changed`: field names and a count, never a value; or
`people.quiet.changed`) and one per refusal."""

import logging
from typing import Any, Literal

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from .. import logs, services
from ..people import model
from ..people.fields import PROFILE_MAX, is_locale, is_location, is_quiet_window, is_timezone
from ..people.household_write import HouseholdWriter
from ..people.people import People, PeopleUnavailable
from .household_models import Household, HouseholdRefused, HouseholdRequest, QuietHours, QuietRefused, QuietWindow
from .models import ErrorResponse
from .person import Person

router = APIRouter()
log = logging.getLogger("ashley.api")
_READ: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "`unauthorized`: no live session"},
    404: {"model": ErrorResponse, "description": "`not_found`: the session's household no longer exists"},
    503: {"model": ErrorResponse, "description": "`unavailable`: the database could not be reached"}}
_WRITE: dict[int | str, dict[str, Any]] = {
    **_READ, 403: {"model": ErrorResponse, "description": "`forbidden`: the request came from another site"},
    422: {"model": HouseholdRefused, "description": "a timezone, locale or location she cannot use; nothing was stored. "
          "A body outside the request's schema gets FastAPI's own validation error, which is not this schema"}}


_QUIET_WRITE: dict[int | str, dict[str, Any]] = {
    **_READ, 403: {"model": ErrorResponse, "description": "`forbidden`: the request came from another site"},
    422: {"model": QuietRefused, "description": "hours or a zone she cannot use; nothing was stored. A body outside "
          "the request's schema gets FastAPI's own validation error, which is not this schema"}}


def _error(status: int, code: Literal["not_found", "unavailable"], detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content=ErrorResponse(code=code, detail=detail).model_dump())


def _wire(h: model.Household) -> Household:
    return Household(id=h.id, name=h.name, timezone=h.timezone, profile=h.profile, profile_limit=PROFILE_MAX,
                     locale=h.locale, unit_system=h.unit_system, clock=h.clock, latitude=h.latitude,
                     longitude=h.longitude)


def _refusal(body: HouseholdRequest) -> Literal["timezone", "locale", "location"] | None:
    if not is_timezone(body.timezone):
        return "timezone"
    if not is_locale(body.locale):
        return "locale"
    return None if is_location(body.latitude, body.longitude) else "location"


@router.get("/api/household", response_model=Household, responses=_READ)
async def read_household(signed_in: Person) -> Household | JSONResponse:
    """200 `Household`; 401 `unauthorized`; 404 `not_found`; 503 `unavailable`."""
    try:
        found = await services.get(People).household(signed_in.person.household_id)
    except PeopleUnavailable:
        return _error(503, "unavailable", "the household is unavailable right now; try again shortly")
    return _error(404, "not_found", "there is no such household") if found is None else _wire(found)


@router.put("/api/household", response_model=Household, responses=_WRITE)
async def write_household(signed_in: Person, body: HouseholdRequest) -> Household | JSONResponse:
    """200 `Household` as stored; 401 `unauthorized`; 403 `forbidden`; 404 `not_found`; 422 `HouseholdRefused`; 503
    `unavailable`."""
    person = signed_in.person
    why = _refusal(body)
    if why is not None:
        logs.info(log, "people.household.refused", household=person.household_id, person=person.id, reason=why)
        return JSONResponse(status_code=422, content=HouseholdRefused(
            invalid=why, detail=f"that is not a {why} she can use").model_dump())
    edit = model.HouseholdEdit(timezone=body.timezone, profile=body.profile, locale=body.locale,
                               unit_system=body.unit_system, clock=body.clock, latitude=body.latitude,
                               longitude=body.longitude)
    try:
        stored = await services.get(HouseholdWriter).put(person.household_id, person.id, edit)
    except PeopleUnavailable:
        return _error(503, "unavailable", "the household is unavailable right now; try again shortly")
    return _error(404, "not_found", "there is no such household") if stored is None else _wire(stored)


@router.get("/api/household/quiet", response_model=QuietHours, responses=_READ)
async def read_quiet(signed_in: Person) -> QuietHours | JSONResponse:
    """200 `QuietHours`; 401 `unauthorized`; 404 `not_found`; 503 `unavailable`."""
    me = signed_in.person
    try:
        found = await services.get(People).household(me.household_id)
    except PeopleUnavailable:
        return _error(503, "unavailable", "the household is unavailable right now; try again shortly")
    mine = None if found is None else next((p for p in found.people if p.id == me.id), None)
    if mine is None:
        return _error(404, "not_found", "there is no such person")
    q = mine.quiet
    return QuietHours(quiet=None if q is None else QuietWindow(start=q.start, end=q.end, timezone=q.timezone))


@router.put("/api/household/quiet", response_model=QuietHours, responses=_QUIET_WRITE)
async def write_quiet(signed_in: Person, body: QuietHours) -> QuietHours | JSONResponse:
    """200 `QuietHours` as stored; 401 `unauthorized`; 403 `forbidden`; 404 `not_found`; 422 `QuietRefused`; 503
    `unavailable`."""
    me = signed_in.person
    w = body.quiet
    if w is not None and not is_quiet_window(w.start, w.end, w.timezone):
        why: Literal["hours", "timezone"] = "timezone" if not is_timezone(w.timezone) else "hours"
        logs.info(log, "people.quiet.refused", household=me.household_id, person=me.id, reason=why)
        return JSONResponse(status_code=422, content=QuietRefused(
            invalid=why, detail=f"those are not {why} she can use").model_dump())
    quiet = None if w is None else model.QuietHours(w.start, w.end, w.timezone)
    try:
        found = await services.get(HouseholdWriter).put_quiet(me.household_id, me.id, quiet)
    except PeopleUnavailable:
        return _error(503, "unavailable", "the household is unavailable right now; try again shortly")
    return body if found else _error(404, "not_found", "there is no such person")
