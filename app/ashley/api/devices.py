"""The household's devices for a signed-in person: `GET /api/devices`. One log line per read, with the household id
and a count; never a token, host or server id."""

import logging
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from .. import logs, services
from ..channels.devices import Devices, DevicesUnavailable
from ..channels.model import Listed
from .models import DevicesResponse, ErrorResponse, ListedDevice
from .person import Person

router = APIRouter()
log = logging.getLogger("ashley.api")
_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "`unauthorized`: no live session"},
    503: {"model": ErrorResponse, "description": "`unavailable`: the database could not be reached"}}


def _wire(listed: Listed) -> ListedDevice:
    d = listed.device
    return ListedDevice(id=d.id, name=d.name, place=d.place, form=listed.form, audience=d.audience, medium=d.medium,
                        takes_controls=listed.takes_controls)


@router.get("/api/devices", response_model=DevicesResponse, responses=_RESPONSES)
async def list_devices(signed_in: Person) -> DevicesResponse | JSONResponse:
    """200 `DevicesResponse`; 401 `unauthorized`; 503 `unavailable`."""
    household = signed_in.person.household_id
    try:
        found = await services.get(Devices).of_household(household)
    except DevicesUnavailable:
        logs.warning(log, "devices.unavailable", household=household)
        return JSONResponse(status_code=503, content=ErrorResponse(
            code="unavailable", detail="devices are unavailable right now; try again shortly").model_dump())
    logs.info(log, "devices.listed", household=household, count=len(found))
    return DevicesResponse(devices=[_wire(listed) for listed in found])
