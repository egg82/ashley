"""The signed-in person's reminders (`decisions.md`, "Reminders are wakes she sets for herself"): `GET /api/reminders`
lists those for them or set by them, still to fire or fired and not delivered, and `DELETE /api/reminders/{id}`
cancels one still to fire, or dismisses one listed as undelivered or failed. Any other id, another person's, another
household's or one delivered, is 404 alike, so nobody learns of a reminder they may not see.
Logs `reminders.listed` with the household and a count and `reminders.cancelled` with the wake id; never what a
reminder says."""

import logging
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Path
from fastapi.responses import JSONResponse

from .. import logs, services
from ..people.people import People, PeopleUnavailable
from ..senses.deposit_rule import describe
from ..senses.repeat import LOCAL_FORMAT
from ..senses.wakes import Scheduled, Wakes, WakesUnavailable
from .models import ErrorResponse, Person as PersonModel
from .person import Person
from .reminder_models import Reminder, ReminderCancelled, RemindersResponse

router = APIRouter()
log = logging.getLogger("ashley.api")
_Id = Annotated[int, Path(ge=1)]
_SIGNED_IN: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "`unauthorized`: no live session"},
    503: {"model": ErrorResponse, "description": "`unavailable`: the database could not be reached"}}


def _error(status: int, code: Literal["not_found", "unavailable"], detail: str) -> JSONResponse:
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
    people = {} if household is None else {p.id: PersonModel(id=p.id, household_id=p.household_id, name=p.name)
                                           for p in household.people}
    zone = ZoneInfo("UTC" if household is None else household.timezone)
    items = [_wire(s, people, zone) for s in found if s.reminder.person_id in people and s.reminder.made_by in people]
    logs.info(log, "reminders.listed", household=me.household_id, count=len(items))
    return RemindersResponse(reminders=items)


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
                    on_deposit=None if s.deposit is None else describe(s.deposit), state=s.state)
