"""The signed-in person's reminders (`decisions.md`, "Reminders are wakes she sets for herself"): `GET /api/reminders`
lists those for them or set by them, still to fire or fired and not delivered, `POST /api/reminders` sets one for
themselves, `PATCH /api/reminders/{id}` sets or clears the method that makes a repeating one a standing errand
(`runs-and-jobs.md`, "A standing errand is a repeating reminder that names her method"), and `DELETE
/api/reminders/{id}` cancels one still to fire, or dismisses one listed as undelivered or failed. Any other id,
another person's, another household's or one delivered, is 404 alike, so nobody learns of a reminder they may not see.
A method is checked as her `remind` tool checks it (`standing_method.named`).
Logs `reminders.listed` with the household and a count, `reminders.created` with the wake id and whether it is a
standing errand, `reminders.method` with the wake id and whether it now has a method, and `reminders.cancelled` with
the wake id; never what a reminder says."""

import logging
from dataclasses import replace
from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Path
from fastapi.responses import JSONResponse

from .. import logs, services
from ..people.people import People, PeopleUnavailable
from ..senses.deposit_rule import describe
from ..senses.repeat import LOCAL_FORMAT
from ..senses.wakes import Reminder as Stored, Scheduled, Wakes, WakesUnavailable
from ..tools import reminder_shape as shape, standing_method
from ..tools.bench_args import BadArguments
from ..tools.tools import ToolsUnavailable
from .models import ErrorResponse, Person as PersonModel, wire_person
from .person import Person
from .reminder_models import Reminder, ReminderCancelled, ReminderMethodRequest, ReminderRequest, RemindersResponse

router = APIRouter()
log = logging.getLogger("ashley.api")
_Id = Annotated[int, Path(ge=1)]
_SIGNED_IN: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "`unauthorized`: no live session"},
    503: {"model": ErrorResponse, "description": "`unavailable`: the database could not be reached"}}


_WRITE: dict[int | str, dict[str, Any]] = {
    **_SIGNED_IN,
    403: {"model": ErrorResponse, "description": "`forbidden`: the request came from another site"},
    422: {"model": ErrorResponse, "description": "`refused`: a time, rule or method that cannot be set, `detail` saying "
                                                 "which (and naming the household's kinds for a method it has none of); "
                                                 "FastAPI's own validation error for a malformed body"}}


def _error(status: int, code: Literal["not_found", "unavailable", "refused"], detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content=ErrorResponse(code=code, detail=detail).model_dump())


@router.get("/api/reminders", response_model=RemindersResponse, responses=_SIGNED_IN)
async def list_reminders(signed_in: Person) -> RemindersResponse | JSONResponse:
    """200 `RemindersResponse`; 401 `unauthorized`; 503 `unavailable`."""
    me = signed_in.person
    try:
        household = await services.get(People).household(me.household_id)
        found = await services.get(Wakes).reminders(me.household_id, me.id)
    except (PeopleUnavailable, WakesUnavailable):
        return _error(503, "unavailable", "reminders are unavailable right now; try again shortly")
    people = {} if household is None else {p.id: wire_person(p)
                                           for p in household.people}
    zone = ZoneInfo("UTC" if household is None else household.timezone)
    items = [_wire(s, people, zone) for s in found if s.reminder.person_id in people and s.reminder.made_by in people]
    logs.info(log, "reminders.listed", household=me.household_id, count=len(items))
    return RemindersResponse(reminders=items)


@router.post("/api/reminders", response_model=Reminder, status_code=201, responses=_WRITE)
async def create_reminder(signed_in: Person, body: ReminderRequest) -> Reminder | JSONResponse:
    """201 `Reminder`, for the signed-in person, to their phone, with no tools beyond the ones that look; 401
    `unauthorized`; 403 `forbidden`; 422 `refused`; 503 `unavailable`."""
    me = signed_in.person
    try:
        household = await services.get(People).household(me.household_id)
        if household is None:
            return _error(503, "unavailable", "reminders are unavailable right now; try again shortly")
        zone = ZoneInfo(household.timezone)
        local = datetime.strptime(body.local_at, LOCAL_FORMAT)
        repeat = None if body.repeat is None else shape.repeat_of({"repeat": body.repeat, "every": body.every}, local, None)
        due_at = shape.first_due(repeat, local, zone, datetime.now(UTC))
        method = await standing_method.named(me.household_id, body.method)
        if method is not None and repeat is None:
            raise BadArguments("a standing errand repeats; give how it repeats, or leave out the method")
        made = await services.get(Wakes).schedule(Stored(me.household_id, me.id, me.id, body.what, due_at, repeat, method=method))
        scheduled = next(s for s in await services.get(Wakes).reminders(me.household_id, me.id) if s.id == made)
    except BadArguments as e:
        return _error(422, "refused", str(e))
    except ValueError:
        return _error(422, "refused", "that time is not a time of day")
    except (PeopleUnavailable, WakesUnavailable, ToolsUnavailable):
        return _error(503, "unavailable", "reminders are unavailable right now; try again shortly")
    logs.info(log, "reminders.created", wake=made, standing=int(method is not None))
    return _wire(scheduled, {p.id: wire_person(p) for p in household.people}, zone)


@router.patch("/api/reminders/{reminder_id}", response_model=Reminder, responses={
    **_WRITE, 404: {"model": ErrorResponse, "description": "`not_found`: no reminder of yours still to fire has that id"}})
async def set_reminder_method(signed_in: Person, reminder_id: _Id, body: ReminderMethodRequest) -> Reminder | JSONResponse:
    """200 `Reminder` with its method set, or cleared by null (an ordinary reminder again, still repeating); 401
    `unauthorized`; 403 `forbidden`; 404 `not_found`, for one that is not theirs or has fired; 422 `refused`, for a
    reminder that does not repeat or a method the household has none of; 503 `unavailable`. Whoever may cancel it may
    change it."""
    me = signed_in.person
    try:
        household = await services.get(People).household(me.household_id)
        wakes = services.get(Wakes)
        found = [s for s in await wakes.reminders(me.household_id, me.id) if s.id == reminder_id and s.state == "scheduled"]
        if household is None or not found:
            return _error(404, "not_found", "no such reminder")
        current = found[0].reminder
        method = await standing_method.named(me.household_id, body.method)
        if method is not None and (current.repeat is None or current.ends_at is not None):
            raise BadArguments("only a repeating reminder can be a standing errand")
        if not await wakes.edit(me.household_id, me.id, reminder_id, replace(current, method=method)):
            return _error(404, "not_found", "no such reminder")
        changed = next(s for s in await wakes.reminders(me.household_id, me.id) if s.id == reminder_id)
    except BadArguments as e:
        return _error(422, "refused", str(e))
    except (PeopleUnavailable, WakesUnavailable, ToolsUnavailable):
        return _error(503, "unavailable", "reminders are unavailable right now; try again shortly")
    logs.info(log, "reminders.method", wake=reminder_id, standing=int(method is not None))
    return _wire(changed, {p.id: wire_person(p) for p in household.people}, ZoneInfo(household.timezone))


@router.delete("/api/reminders/{reminder_id}", response_model=ReminderCancelled, responses={
    **_SIGNED_IN,
    403: {"model": ErrorResponse, "description": "`forbidden`: the request came from another site"},
    404: {"model": ErrorResponse, "description": "`not_found`: no reminder of yours listed has that id"},
    422: {"description": "FastAPI's validation error: an id below 1"}})
async def cancel_reminder(signed_in: Person, reminder_id: _Id) -> ReminderCancelled | JSONResponse:
    """200 `ReminderCancelled`; 401 `unauthorized`; 403 `forbidden`; 404 `not_found`; 503 `unavailable`."""
    me = signed_in.person
    try:
        wakes = services.get(Wakes)
        cancelled = await wakes.cancel(me.household_id, me.id, reminder_id) or \
            await wakes.dismiss(me.household_id, me.id, reminder_id)
    except WakesUnavailable:
        return _error(503, "unavailable", "reminders are unavailable right now; try again shortly")
    if not cancelled:
        return _error(404, "not_found", "no such reminder")
    logs.info(log, "reminders.cancelled", wake=reminder_id)
    return ReminderCancelled(id=reminder_id)


def _wire(s: Scheduled, people: dict[int, PersonModel], zone: ZoneInfo) -> Reminder:
    r = s.reminder
    return Reminder(id=s.id, person=people[r.person_id], made_by=people[r.made_by], what=r.brief, due_at=r.due_at,
                    local_at=r.due_at.astimezone(zone).strftime(LOCAL_FORMAT),
                    repeat=None if r.repeat is None else r.repeat.freq,
                    every=None if r.repeat is None else r.repeat.every,
                    on_deposit=None if s.deposit is None else describe(s.deposit), method=r.method, state=s.state)
