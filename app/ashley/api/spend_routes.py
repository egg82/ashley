"""The Usage room's model choices: a signed-in person reads and sets which model carries each chat-facing task for
their own household (`ashley.inference.household_routes`). The household is always the session's, so no route names or
reaches another's. Only this route and the wiring reach `RouteChoiceWriter`, so nothing she does on her own chooses a
model (`tests/test_settings_boundary.py`).

`GET /api/spend/routes` answers every task the household may choose for, then `action_judge`, read-only.
`PUT /api/spend/routes/{task}` stores or clears the choice for one task and answers the same as GET. A choice that is
not one of the task's options now is 422 `SpendRouteRefused` and nothing is stored. A choice reaches every reply within
`refresh_s`.

One log line per write (the writer's `inference.choice_set`) and one per refusal (`inference.choice_refused`: household,
person, task, reason)."""

import logging
from typing import Any, Literal

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from .. import logs, services
from ..inference.household_routes import HouseholdRoutes, TaskChoices
from ..inference.layered_routes import REFRESH_S
from ..inference.model import Route, Task
from ..inference.route_choice_write import RouteChoiceWriter
from ..inference.route_choices import Choice, RoutesUnavailable
from .models import ErrorResponse
from .person import Person
from .spend_routes_models import RouteModel, SpendRouteRefused, SpendRouteRequest, SpendRoutesResponse, TaskRoutes

router = APIRouter()
log = logging.getLogger("ashley.api")
_READ: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "`unauthorized`: no live session"},
    503: {"model": ErrorResponse, "description": "`unavailable`: the choices could not be read or written"}}
_WRITE: dict[int | str, dict[str, Any]] = {
    **_READ, 403: {"model": ErrorResponse, "description": "`forbidden`: the request came from another site"},
    422: {"model": SpendRouteRefused, "description": "a choice the task does not offer now; nothing was stored. A body "
          "or task outside the request's schema gets FastAPI's own validation error, which is not this schema"}}


def _unavailable() -> JSONResponse:
    return JSONResponse(status_code=503, content=ErrorResponse(
        code="unavailable", detail="model choices are unavailable right now; try again shortly").model_dump())


def _route(r: Route | Choice) -> RouteModel:
    return RouteModel(provider=r.provider, model=r.model)


def _task(t: TaskChoices) -> TaskRoutes:
    return TaskRoutes(task=t.task, household=t.household, routes=[_route(r) for r in t.routes],
                      chosen=None if t.chosen is None else _route(t.chosen), options=[_route(r) for r in t.options])


async def _read(household_id: int) -> SpendRoutesResponse | JSONResponse:
    try:
        found = await services.get(HouseholdRoutes).choices(household_id)
    except RoutesUnavailable:
        return _unavailable()
    return SpendRoutesResponse(choices=[_task(t) for t in found], refresh_s=round(REFRESH_S))


_DETAIL: dict[Literal["not_household", "not_offered", "unwired"], str] = {
    "not_household": "a household does not choose the model for that task",
    "not_offered": "that model is not one this task offers",
    "unwired": "that model's provider has no key right now"}


@router.get("/api/spend/routes", response_model=SpendRoutesResponse, responses=_READ)
async def read_routes(signed_in: Person) -> SpendRoutesResponse | JSONResponse:
    """200 `SpendRoutesResponse`; 401 `unauthorized`; 503 `unavailable`."""
    return await _read(signed_in.person.household_id)


@router.put("/api/spend/routes/{task}", response_model=SpendRoutesResponse, responses=_WRITE)
async def write_route(signed_in: Person, task: Task, body: SpendRouteRequest) -> SpendRoutesResponse | JSONResponse:
    """200 `SpendRoutesResponse` as stored; 401 `unauthorized`; 403 `forbidden`; 422 `SpendRouteRefused`; 503
    `unavailable`."""
    person = signed_in.person
    choice = None if body.route is None else Choice(body.route.provider, body.route.model)
    why = services.get(HouseholdRoutes).refusal(task, choice)
    if why is not None:
        logs.info(log, "inference.choice_refused", household=person.household_id, person=person.id, task=task,
                  reason=why)
        return JSONResponse(status_code=422, content=SpendRouteRefused(reason=why, detail=_DETAIL[why]).model_dump())
    try:
        await services.get(RouteChoiceWriter).put(person.household_id, person.id, task, choice)
    except RoutesUnavailable:
        return _unavailable()
    return await _read(person.household_id)
