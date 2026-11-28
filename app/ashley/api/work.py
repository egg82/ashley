"""The signed-in person's open work (`GET /api/work`): the errands they asked for that have not ended, their open
benches, the proposals waiting for their OK, the watches she keeps for them and what she did on her own for them, each with where it stands and its lane
(`work_items`), and `DELETE /api/work/watches/{id}`, which ends one of their live watches. A watch that is not theirs,
is another household's, has ended or is unknown is 404 alike. Logs `work.listed` with the household and a count and
`work.watch_cancelled` with the watch id; never what an item says."""

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Path
from fastapi.responses import JSONResponse

from .. import logs
from ..channels.board import BoardUnavailable, end_watch
from ..errands.bench_jobs import JobsUnavailable
from ..errands.errands import ErrandsUnavailable
from ..people.people import PeopleUnavailable
from ..senses.wakes import WakesUnavailable
from ..workshop.workshop import WorkshopUnavailable
from .benches import owner_of
from .models import ErrorResponse
from .person import Person
from .work_items import open_work
from .work_models import WatchCancelled, WorkResponse

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
    except (ErrandsUnavailable, WakesUnavailable, JobsUnavailable, WorkshopUnavailable, PeopleUnavailable, BoardUnavailable):
        return JSONResponse(status_code=503, content=ErrorResponse(
            code="unavailable", detail="her work is unavailable right now; try again shortly").model_dump())
    logs.info(log, "work.listed", household=owner.household_id, count=len(items))
    return WorkResponse(entries=items)


@router.delete("/api/work/watches/{watch_id}", response_model=WatchCancelled, responses={
    **_SIGNED_IN,
    403: {"model": ErrorResponse, "description": "`forbidden`: the request came from another site"},
    404: {"model": ErrorResponse, "description": "`not_found`: no live watch of yours has that id"},
    422: {"description": "FastAPI's validation error: an id below 1"}})
async def cancel_watch(signed_in: Person, watch_id: Annotated[int, Path(ge=1)]) -> WatchCancelled | JSONResponse:
    """200 `WatchCancelled`, the watch ended as disarmed; 401 `unauthorized`; 403 `forbidden`; 404 `not_found`; 503
    `unavailable`."""
    me = signed_in.person
    try:
        ended = await end_watch(me.household_id, me.id, watch_id)
    except BoardUnavailable:
        return JSONResponse(status_code=503, content=ErrorResponse(
            code="unavailable", detail="her watches are unavailable right now; try again shortly").model_dump())
    if not ended:
        return JSONResponse(status_code=404, content=ErrorResponse(code="not_found", detail="no such watch").model_dump())
    logs.info(log, "work.watch_cancelled", watch=watch_id)
    return WatchCancelled(id=watch_id)
