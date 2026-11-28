"""The signed-in person's open work (`GET /api/work`): the errands they asked for that have not ended, their open
benches, the proposals waiting for their OK, the watches she keeps for them and what she did on her own for them, each with where it stands and its lane
(`work_items`), `DELETE /api/work/watches/{id}`, which ends one of their live watches, and
`POST /api/work/actions/{id}/undo`, which takes back something she did on her own for them through her own tool for it
(`channels.undo_action`). A watch or action that is not theirs, is another household's or is unknown is 404 alike, as
is a watch that has ended. Logs `work.listed` with the household and a count and `work.watch_cancelled` with the watch
id; never what an item says. An undo logs its own `undo.done`."""

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Path
from fastapi.responses import JSONResponse

from .. import logs
from ..channels.board import BoardUnavailable, end_watch
from ..channels.model import Inbound
from ..channels.undo_action import Refusal, UndoNotFound, UndoRefused, UndoUnavailable, undo
from ..errands.bench_jobs import JobsUnavailable
from ..errands.errands import ErrandsUnavailable
from ..people.people import PeopleUnavailable
from ..senses.wakes import WakesUnavailable
from ..workshop.workshop import WorkshopUnavailable
from .benches import owner_of
from .models import ErrorResponse
from .person import Person
from .work_items import open_work
from .chat import thread_of
from .work_models import UndoDone, WatchCancelled, WorkResponse

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


_UNDO_REFUSED: dict[Refusal, ErrorResponse] = {
    "no_undo": ErrorResponse(code="no_undo", detail="that cannot be undone"),
    "already_undone": ErrorResponse(code="already_undone", detail="that was already undone, or is being undone now"),
    "failed": ErrorResponse(code="refused", detail="that could not be undone; nothing was changed")}


@router.post("/api/work/actions/{action_id}/undo", response_model=UndoDone, responses={
    **_SIGNED_IN,
    403: {"model": ErrorResponse, "description": "`forbidden`: the request came from another site"},
    404: {"model": ErrorResponse, "description": "`not_found`: no action she took for you has that id"},
    409: {"model": ErrorResponse, "description": "`no_undo`: it has no undo; `already_undone`: its undo was taken; "
          "`refused`: her tool for that change refused it or could not make it. Nothing was changed"},
    422: {"description": "FastAPI's validation error: an id below 1"}})
async def undo_action(signed_in: Person, action_id: Annotated[int, Path(ge=1)]) -> UndoDone | JSONResponse:
    """200 `UndoDone`; 401 `unauthorized`; 403 `forbidden`; 404 `not_found`; 409 `no_undo`, `already_undone` or
    `refused`; 503 `unavailable`, with nothing changed."""
    me = signed_in.person
    inbound = Inbound(household_id=me.household_id, thread=thread_of(signed_in), text="", kind="chat", medium="text",
                      audience="owner", speaker_id=me.id, shared=False, place=None, channel="web", later=True,
                      later_by="turn", on_page=True, taint=None)
    try:
        done = await undo(inbound, action_id)
    except UndoNotFound:
        return JSONResponse(status_code=404, content=ErrorResponse(code="not_found", detail="no such action").model_dump())
    except UndoRefused as e:
        return JSONResponse(status_code=409, content=_UNDO_REFUSED[e.reason].model_dump())
    except UndoUnavailable:
        return JSONResponse(status_code=503, content=ErrorResponse(
            code="unavailable", detail="that cannot be undone right now; try again shortly").model_dump())
    return UndoDone(id=action_id, how=done.outcome, conversation_id=done.conversation_id)
