"""A person's house routes: the household's lights and scenes pressed from any signed-in screen, and the house at a glance.
`GET /api/house/controls` lists them (`channels.kiosk.house_controls`, the catalogue limited to what the kiosk's `ACTIONS`
allow); `POST /api/house/controls/{name}` presses one by that name alone, carried out by code as a kiosk's press is
(`channels.kiosk.controls.run`, through `house_do`), so `irreversible.json` and the tool's other checks apply unchanged.
A press is the person's own act, not hers: it is not an outside action, and the log line names the person. Each press
counts against the person's rate (`Sessions.allow`). `GET /api/house/glance` is who is home (`channels.kiosk.glance`) and
what needs the person (`house_attention`). `GET /api/house/printers` is the household's printers as their cards show them
(`house_printers`).

The wire shapes are the kiosk's controls' (`KioskControls`, `KioskControlDone`), so one client part reads either.

Logs `kiosk.control` with the person id on a press, `house.refused` with the person id and reason `rate`."""

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Path
from fastapi.responses import JSONResponse

from .. import logs, services
from ..channels.kiosk import controls, house_controls
from ..channels.kiosk.glance import glance
from ..channels.kiosk.controls import lights_on
from ..connections.connections import ConnectionsUnavailable
from ..connections.kinds import CatalogueUnavailable
from ..signin.sessions import Sessions, SessionsUnavailable
from .benches import owner_of
from .house_attention import attention
from .house_models import HouseGlance, HousePrinters
from .house_printers import printers
from .models import ErrorResponse, KioskControl, KioskControlDone, KioskControls
from .person import Person

router = APIRouter()
log = logging.getLogger("ashley.api")
_READ: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "`unauthorized`: no live session"},
    503: {"model": ErrorResponse, "description": "`unavailable`: a system it needs could not be reached"}}
_PRESS: dict[int | str, dict[str, Any]] = {
    **_READ, 403: {"model": ErrorResponse, "description": "`forbidden`: from another site, or not JSON"},
    404: {"model": ErrorResponse, "description": "`not_found`: the household has no light or scene of that name"},
    422: {"model": ErrorResponse, "description": "a name outside `[a-z0-9-]{1,40}` gets FastAPI's own validation "
          "error, which is not this schema"},
    429: {"model": ErrorResponse, "description": "`rate_limited`: the person is over their rate"}}


def _unavailable() -> JSONResponse:
    return JSONResponse(status_code=503, content=ErrorResponse(
        code="unavailable", detail="the house is unavailable right now; try again shortly").model_dump())


@router.get("/api/house/controls", response_model=KioskControls, responses=_READ)
async def house_controls_listed(signed_in: Person) -> KioskControls | JSONResponse:
    """200 `KioskControls`, the household's lights and scenes, each light with whether it is on; 401 `unauthorized`;
    503 `unavailable`."""
    me = signed_in.person
    try:
        found = await house_controls.listed(me.household_id, me.id)
    except (ConnectionsUnavailable, CatalogueUnavailable):
        return _unavailable()
    lit = await lights_on(me.household_id, (c.entity_id for c in found if c.action == "light.toggle"))
    return KioskControls(controls=[
        KioskControl(name=c.id, label=c.label, on=lit.get(c.entity_id) if c.action == "light.toggle" else None)
        for c in found])


@router.post("/api/house/controls/{name}", response_model=KioskControlDone, responses=_PRESS)
async def house_control_pressed(signed_in: Person,
                                name: Annotated[str, Path(pattern=r"^[a-z0-9-]{1,40}$")]) -> KioskControlDone | JSONResponse:
    """200 `KioskControlDone`; 401 `unauthorized`; 403 `forbidden`; 404 `not_found`; 422 FastAPI's validation error;
    429 `rate_limited`; 503 `unavailable`."""
    me = signed_in.person
    try:
        found = next((c for c in await house_controls.listed(me.household_id, me.id) if c.id == name), None)
    except (ConnectionsUnavailable, CatalogueUnavailable):
        return _unavailable()
    if found is None:
        return JSONResponse(status_code=404, content=ErrorResponse(code="not_found", detail="no such control")
                            .model_dump())
    try:
        allowed = await services.get(Sessions).allow(me.household_id, me.id)
    except SessionsUnavailable:
        return _unavailable()
    if not allowed:
        logs.info(log, "house.refused", person=me.id, reason="rate")
        return JSONResponse(status_code=429, content=ErrorResponse(
            code="rate_limited", detail="too many requests; slow down").model_dump())
    return KioskControlDone(done=await controls.run(found, None, me.household_id, me.id))


@router.get("/api/house/glance", response_model=HouseGlance, responses={401: _READ[401]})
async def house_glance(signed_in: Person) -> HouseGlance:
    """200 `HouseGlance`; 401 `unauthorized`. A part that cannot be read is null in it."""
    me = signed_in.person
    seen = await glance(me.household_id)
    return HouseGlance(home=None if seen.home is None else list(seen.home),
                       needs_attention=await attention(owner_of(signed_in)))


@router.get("/api/house/printers", response_model=HousePrinters, responses={401: _READ[401]})
async def house_printers(signed_in: Person) -> HousePrinters:
    """200 `HousePrinters`; 401 `unauthorized`. Printers that cannot be read are null, never an empty list."""
    return await printers(signed_in.person.household_id)
