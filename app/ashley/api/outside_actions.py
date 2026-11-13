"""What she did on her own for the signed-in person (`decisions.md`, "A turn that has read outside words asks before it
does anything consequential the person did not ask for"): `GET /api/outside-actions` lists the changes made with no OK,
newest first, from `outside_actions`. Only the person's own rows are served: a summary is written for the person alone.
Logs `outside_actions.listed` with the household and a count; never a summary."""

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from .. import logs, services
from ..senses.outside_record import OutsideRecord, OutsideRecordUnavailable
from .models import ErrorResponse
from .outside_models import OutsideAction, OutsideActionsResponse
from .person import Person

router = APIRouter()
log = logging.getLogger("ashley.api")
_SIGNED_IN: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "`unauthorized`: no live session"},
    503: {"model": ErrorResponse, "description": "`unavailable`: the database could not be reached"}}


@router.get("/api/outside-actions", response_model=OutsideActionsResponse, responses={
    **_SIGNED_IN, 422: {"description": "FastAPI's validation error: a `limit` outside 1 to 200"}})
async def list_outside_actions(signed_in: Person, limit: Annotated[int, Query(ge=1, le=200)] = 100) -> OutsideActionsResponse | JSONResponse:
    """200 `OutsideActionsResponse`; 401 `unauthorized`; 503 `unavailable`; 422 for a `limit` outside 1 to 200."""
    me = signed_in.person
    try:
        found = await services.get(OutsideRecord).of_person(me.household_id, me.id, limit)
    except OutsideRecordUnavailable:
        return JSONResponse(status_code=503, content=ErrorResponse(
            code="unavailable", detail="what she did on her own is unavailable right now; try again shortly").model_dump())
    logs.info(log, "outside_actions.listed", household=me.household_id, count=len(found))
    return OutsideActionsResponse(outside_actions=[
        OutsideAction(id=r.id, label=r.action.label or None, summary=r.action.summary, tier="runs" if r.action.tier == "runs" else "judged",
                      explanation=r.action.explanation or None, at=r.action.at) for r in found])
