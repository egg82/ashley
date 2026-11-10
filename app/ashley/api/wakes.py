"""Home Assistant waking her: `POST /api/wakes`, called by HA's `rest_command.ashley_wake` with the house's device
token (`python -m ashley.channels.devices add`, then `house`), signed in as any device is (`messages.signed_in`: a
bearer token, LAN only, the device's rate), and refused 403 unless that device is the house: a satellite, the tablet
or a Discord server cannot wake her. The wake is stored (`Wakes.receive`) and answered 202 at once, so HA never waits on a model;
the `wakes` singleton takes it up (`ashley.channels.wake.runner`). The same event id again is 202 `duplicate`, so a
retry or a second delivery is one wake. Logs `wakes.received` with the device and wake ids and `duplicate`, never a
field of the wake."""

import logging
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from .. import logs, services
from ..channels.devices import Devices, DevicesUnavailable
from ..channels.model import Device
from ..senses.wakes import Wake, Wakes, WakesUnavailable
from .messages import signed_in
from .models import ErrorResponse
from .wake_models import WakeAccepted, WakeRequest

router = APIRouter()
log = logging.getLogger("ashley.api.wakes")


@router.post("/api/wakes", status_code=202, response_model=WakeAccepted, responses={
    401: {"model": ErrorResponse, "description": "`unauthorized`; also a device token sent from the public internet"},
    403: {"model": ErrorResponse, "description": "`forbidden`; the device is not the house (`devices house`)"},
    422: {"description": "FastAPI's validation error: a field outside `WakeRequest`, or one holding free text"},
    429: {"model": ErrorResponse, "description": "`rate_limited`; the device is over its rate"},
    503: {"model": ErrorResponse, "description": "`unavailable`; the wake could not be stored"},
})
async def post_wake(device: Annotated[Device, Depends(signed_in)], body: WakeRequest) -> WakeAccepted | JSONResponse:
    """202 `WakeAccepted`; 401 `unauthorized`; 403 `forbidden` for a device that is not the house; 422 FastAPI's
    validation error; 429 `rate_limited`; 503 `unavailable`."""
    try:
        house = await _is_house(device)
    except DevicesUnavailable:
        return _error(503, "unavailable", "the device could not be checked; try again shortly")
    if not house:
        logs.info(log, "api.device_refused", device=device.id, reason="not_house")
        return _error(403, "forbidden", "only the house's device hands in wakes")
    wake = Wake(device.household_id, body.event_id, body.event, body.who, body.what, body.when or datetime.now(UTC))
    try:
        got = await services.get(Wakes).receive(device.id, wake)
    except WakesUnavailable:
        return _error(503, "unavailable", "the wake could not be stored; try again shortly")
    logs.info(log, "wakes.received", device=device.id, wake=got.id, duplicate=not got.new)
    return WakeAccepted(id=got.id, duplicate=not got.new)


async def _is_house(device: Device) -> bool:
    listed = await services.get(Devices).of_household(device.household_id)
    return any(d.device.id == device.id and d.form == "house" for d in listed)


def _error(status: int, code: Literal["forbidden", "unavailable"], detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content=ErrorResponse(code=code, detail=detail).model_dump())
