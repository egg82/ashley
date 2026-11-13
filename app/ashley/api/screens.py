"""`POST /api/screens/visibility`: the signed-in person's page says whether it is in the foreground, against the token it
opened its feed under (`GET /api/live?screen=`). The report lands in the open-screens record every pod reads
(`ashley.live.screens.Screens`); a token that names none of this person's open screens changes nothing and still answers
204, since the page may report an instant before its feed opens. The kiosk's own route is `POST /api/kiosk/screen`.

Logs `screens.visibility` with the person id and the visibility; `screens.unavailable` when the record cannot be reached."""

import logging
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse, Response

from .. import logs, services
from ..live.screens import Screens, ScreensUnavailable
from .live_models import ScreenVisibility
from .models import ErrorResponse
from .person import Person

router = APIRouter()
log = logging.getLogger("ashley.api.screens")
UNAVAILABLE: dict[int | str, dict[str, Any]] = {
    503: {"model": ErrorResponse, "description": "`unavailable`: the record of open screens could not be reached"}}


def unavailable() -> JSONResponse:
    logs.warning(log, "screens.unavailable")
    return JSONResponse(status_code=503, content=ErrorResponse(
        code="unavailable", detail="open screens cannot be recorded right now").model_dump())


@router.post("/api/screens/visibility", status_code=204, response_class=Response, responses={
    401: {"model": ErrorResponse, "description": "`unauthorized`: no live session"},
    403: {"model": ErrorResponse, "description": "`forbidden`: the request came from another site or was not JSON"},
    **UNAVAILABLE})
async def report_visibility(body: ScreenVisibility, signed_in: Person) -> Response:
    """204; 401 `unauthorized`; 403 `forbidden`; 422 FastAPI's validation error for a body outside
    `ScreenVisibility`; 503 `unavailable`."""
    who = signed_in.person
    try:
        await services.get(Screens).person_visible(who.id, str(body.screen), body.visible)
    except ScreensUnavailable:
        return unavailable()
    logs.info(log, "screens.visibility", person=who.id, visible=body.visible)
    return Response(status_code=204)
