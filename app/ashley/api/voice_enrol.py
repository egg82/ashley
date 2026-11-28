"""Arming a speaker to enrol the signed-in person's voice: `POST /api/memory/voice/enrolments` (`decisions.md`, "A voice
names the speaker as a hint"). The rules are the admin CLI's `voice-enrol`: the device must be one of the person's
household and a satellite, `until` and the default `wakes` come from the voice config. The person is the session's;
nobody can arm another."""

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from .. import logs, services
from ..channels.devices import Devices, DevicesUnavailable
from ..channels.voice import config as voice_config
from ..channels.voice.voices import UnknownEnrolee, Voices, VoicesUnavailable
from .models import ErrorResponse
from .person import Person
from .voice_models import Enrolment, EnrolmentRequest

router = APIRouter()
log = logging.getLogger("ashley.api")
_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "`unauthorized`: no live session"},
    403: {"model": ErrorResponse, "description": "`forbidden`: the request came from another site or was not JSON"},
    404: {"model": ErrorResponse, "description": "`not_found`: no unrevoked device of your household has that id"},
    409: {"model": ErrorResponse, "description": "`refused`: the device is not a voice satellite"},
    422: {"model": ErrorResponse, "description": "a body outside the request model gets FastAPI's own validation error, "
          "which is not this schema"},
    503: {"model": ErrorResponse, "description": "`unavailable`: the database could not be reached"}}


def _error(status: int, code: str, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"code": code, "detail": detail})


@router.post("/api/memory/voice/enrolments", status_code=201, response_model=Enrolment, responses=_RESPONSES)
async def arm_enrolment(body: EnrolmentRequest, signed_in: Person) -> Enrolment | JSONResponse:
    """201 `Enrolment`, the device armed for the signed-in person (replacing any enrolment it already had); 401
    `unauthorized`; 403 `forbidden`; 404 `not_found`; 409 `refused`; 503 `unavailable`."""
    person = signed_in.person
    config = voice_config.load()
    wakes = config.enrol_wakes if body.wakes is None else body.wakes
    until = datetime.now(UTC) + timedelta(minutes=config.enrol_minutes)
    try:
        listed = next((d for d in await services.get(Devices).of_household(person.household_id)
                       if d.device.id == body.device_id), None)
        if listed is None:
            return _error(404, "not_found", "no such device")
        if listed.form != "satellite":
            return _error(409, "refused", "only a voice satellite can enrol a voice")
        await services.get(Voices).arm(body.device_id, person.id, wakes, until)
    except UnknownEnrolee:
        return _error(404, "not_found", "no such device")
    except (DevicesUnavailable, VoicesUnavailable):
        return _error(503, "unavailable", "voice enrolment is unavailable right now; try again shortly")
    logs.info(log, "voice.enrolment_armed", household=person.household_id, person=person.id, device=body.device_id,
              wakes=wakes)
    return Enrolment(device_id=body.device_id, wakes=wakes, until=until)
