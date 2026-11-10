"""A device's touch controls for a signed-in person of its household: `GET` and `PUT /api/devices/{id}/controls`. The list
is the body of the device's screen's `controls` piece (`Workshop.screen`), and `PUT` replaces the whole of it as an Edit
of that piece naming the `version` read (`base_version`), so of two edits made from one read the second is refused 409
`stale` and the editor reads again. Every light must be one the house's catalogue (`ConnectionKind.catalogue`, read now
from the household's connections) has, in the action's domain, else 422 `ControlsRefused` and nothing is stored. A device
of another household is 404, as is one that is revoked. Any person of the household may edit.

One log line per write (the Workshop's `workshop.command`) and one per refusal, with the device id and the reason; never
labels or entity ids."""

import logging
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Path
from fastapi.responses import JSONResponse

from .. import logs, services
from ..channels.devices import Devices, DevicesUnavailable
from ..channels.kiosk.controls import Control, ControlRefused, Wanted, validate
from ..channels.kiosk.house_domains import domains
from ..channels.kiosk.screen_controls_of import controls_piece
from ..connections.connections import ConnectionsUnavailable
from ..connections.kinds import CatalogueUnavailable
from ..workshop.commands import Add, Added, Edit, ScreenCommand
from ..workshop.model import By, Text
from ..workshop.rules import load_screen
from ..workshop.screen_controls import encode
from ..workshop.workshop import Applied, ScreenNotFound, ScreenView, Workshop, WorkshopUnavailable
from .device_control_models import ControlsRefused, DeviceControl, DeviceControlList, DeviceControlsRequest
from .models import ErrorResponse
from .person import Person

router = APIRouter()
log = logging.getLogger("ashley.api")
_READ: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "`unauthorized`: no live session"},
    404: {"model": ErrorResponse, "description": "`not_found`: the household has no such device"},
    422: {"model": ErrorResponse, "description": "a device id outside its bounds gets FastAPI's own validation error, "
          "which is not this schema"},
    503: {"model": ErrorResponse, "description": "`unavailable`: the database or the house could not be reached"}}
_WRITE: dict[int | str, dict[str, Any]] = {
    **_READ, 403: {"model": ErrorResponse, "description": "`forbidden`: the request came from another site"},
    409: {"model": ErrorResponse, "description": "`stale`: the list changed since `base_version`; nothing was stored"},
    422: {"model": ControlsRefused, "description": "the controls are not storable; nothing was. A body outside the "
          "request's schema gets FastAPI's own validation error, which is not this schema"}}
DeviceId = Annotated[int, Path(ge=1)]
_TITLE = load_screen().kinds["controls"].label


def _error(status: int, code: Literal["not_found", "unavailable", "stale"], detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content=ErrorResponse(code=code, detail=detail).model_dump())


def _wire(controls: tuple[Control, ...], version: int) -> DeviceControlList:
    return DeviceControlList(device_controls=[DeviceControl(name=c.id, label=c.label, action=c.action, entity_id=c.entity_id)
                                              for c in controls], piece_version=version)


def _reported(view: ScreenView) -> tuple[tuple[Control, ...], int]:
    """The list and version an editor is shown: version 0 until the screen is laid out, when its controls piece is only
    the seed, and while it has no controls piece."""
    piece = controls_piece(view)
    if piece is None:
        return (), 0
    return piece[2], piece[1] if view.laid_out else 0


@router.get("/api/devices/{device_id}/controls", response_model=DeviceControlList, responses=_READ)
async def read_controls(signed_in: Person, device_id: DeviceId) -> DeviceControlList | JSONResponse:
    """200 `DeviceControlList`; 401 `unauthorized`; 404 `not_found`; 422 FastAPI's validation error; 503
    `unavailable`."""
    household = signed_in.person.household_id
    try:
        if not await _is_theirs(household, device_id):
            return _error(404, "not_found", "the household has no such device")
        return _wire(*_reported(await services.get(Workshop).screen(household, device_id)))
    except ScreenNotFound:
        return _error(404, "not_found", "the household has no such device")
    except (WorkshopUnavailable, DevicesUnavailable):
        return _error(503, "unavailable", "the controls are unavailable right now; try again shortly")


async def _is_theirs(household_id: int, device_id: int) -> bool:
    """Whether the household has an unrevoked device `device_id`. Raises DevicesUnavailable."""
    return any(listed.device.id == device_id for listed in await services.get(Devices).of_household(household_id))


def _command(person_id: int, view: ScreenView, base_version: int, controls: tuple[Control, ...]) -> ScreenCommand | None:
    """The Command that stores `controls` over the list read at `base_version`; None when the list is no longer at it."""
    body = encode(controls)
    piece = next((p for p in view.pieces if p.kind == "controls"), None)
    if piece is None:
        return Add(By(person_id), "controls", Text(_TITLE, body), "medium") if base_version == 0 else None
    if base_version != (piece.version if view.laid_out else 0):
        return None
    return Edit(By(person_id), piece.id, piece.version, Text(piece.text.title, body))


def _stored(applied: Applied, command: ScreenCommand, controls: tuple[Control, ...]) -> DeviceControlList | JSONResponse:
    """The reply to an applied PUT: the list and its new version, or the refusal."""
    if applied.outcome == "accepted":
        effect = applied.effect
        version = effect.piece.version if isinstance(effect, Added) else command.base_version + 1 if isinstance(command, Edit) else 1
        return _wire(controls, version)
    if applied.outcome in ("stale_base", "no_such_piece"):
        return _error(409, "stale", "the controls changed since you read them; read them again")
    reason = applied.outcome if applied.outcome in ("required", "full", "already_shown") else "too_many"
    return JSONResponse(status_code=422, content=ControlsRefused(reason=reason, detail="those controls cannot be stored").model_dump())


@router.put("/api/devices/{device_id}/controls", response_model=DeviceControlList, responses=_WRITE)
async def write_controls(signed_in: Person, device_id: DeviceId,
                         body: DeviceControlsRequest) -> DeviceControlList | JSONResponse:
    """200 `DeviceControlList` as stored, its `version` the new one; 401 `unauthorized`; 403 `forbidden`; 404 `not_found`;
    409 `stale`; 422 `ControlsRefused`, or FastAPI's validation error; 503 `unavailable`."""
    person = signed_in.person
    try:
        if not await _is_theirs(person.household_id, device_id):
            return _error(404, "not_found", "the household has no such device")
        wanted = [Wanted(w.name, w.label, w.action, w.entity_id) for w in body.wanted]
        controls = validate(wanted, await domains(person.household_id, person.id) if wanted else {})
        workshop = services.get(Workshop)
        command = _command(person.id, await workshop.screen(person.household_id, device_id), body.base_version, controls)
        if command is None:
            return _error(409, "stale", "the controls changed since you read them; read them again")
        return _stored(await workshop.apply_screen(person.household_id, device_id, command), command, controls)
    except ControlRefused as e:
        logs.info(log, "device_controls.refused", household=person.household_id, person=person.id, device=device_id,
                  reason=e.reason)
        return JSONResponse(status_code=422, content=ControlsRefused(
            reason=e.reason, detail="those controls cannot be stored").model_dump())
    except ScreenNotFound:
        return _error(404, "not_found", "the household has no such device")
    except (WorkshopUnavailable, DevicesUnavailable, ConnectionsUnavailable, CatalogueUnavailable):
        logs.info(log, "device_controls.unavailable", household=person.household_id, device=device_id)
        return _error(503, "unavailable", "the controls are unavailable right now; try again shortly")
