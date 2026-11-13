"""The signed-in person's open work (`GET /api/work`): the errands they asked for that have not ended and their open
benches, each with where it stands (`work_items`). Logs `work.listed` with the household and a count; never what an
item says."""

import logging
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from .. import logs
from ..errands.bench_jobs import JobsUnavailable
from ..errands.errands import ErrandsUnavailable
from ..people.people import PeopleUnavailable
from ..senses.wakes import WakesUnavailable
from ..workshop.workshop import WorkshopUnavailable
from .benches import owner_of
from .models import ErrorResponse
from .person import Person
from .work_items import open_work
from .work_models import WorkResponse

router = APIRouter()
log = logging.getLogger("ashley.api")
_SIGNED_IN: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "`unauthorized`: no live session"},
    503: {"model": ErrorResponse, "description": "`unavailable`: a store holding part of it could not be reached"}}


@router.get("/api/work", response_model=WorkResponse, responses=_SIGNED_IN)
async def list_work(signed_in: Person) -> WorkResponse | JSONResponse:
    """200 `WorkResponse`; 401 `unauthorized`; 503 `unavailable`. All of it or none: a part that cannot be read is not
    shown as an empty one."""
    owner = owner_of(signed_in)
    try:
        items = await open_work(owner)
    except (ErrandsUnavailable, WakesUnavailable, JobsUnavailable, WorkshopUnavailable, PeopleUnavailable):
        return JSONResponse(status_code=503, content=ErrorResponse(
            code="unavailable", detail="her work is unavailable right now; try again shortly").model_dump())
    logs.info(log, "work.listed", household=owner.household_id, count=len(items))
    return WorkResponse(entries=items)
