"""The kiosk, a channel adapter for a shared screen (the hallway tablet) signed in as a device (`kiosk_device`). It
shows shared things only: its own conversation, on the device's thread `device:<id>` as `POST /api/messages` uses, a
glance (`channels.kiosk.glance`), its layout (`GET /api/kiosk/layout`, the device's screen bench) and the touch controls of that screen's `controls` piece, carried out by code (`channels.kiosk.controls`), and what changed
on its screen, as Server-Sent Events like `GET /api/live` but seen as the device: the household's shared events and its
own thread's turns, never one on a person's channel (`ashley.live.events.shown_to`).

A message is the device's: channel `web`, the device's audience and place, shared, so presence names the speaker as on
any shared device; in text, since it is read on a screen. A reply that only says she will check comes back at once
(`follows`); the answer is stored as her turn and announced to the device's screen on `GET /api/kiosk/live`, not queued
in the `Outbox`, whose `device:` replies belong to the satellites singleton, which takes every one of them.

Logs `kiosk.paired` with the device id when a screen pairs; never the token or what was said."""

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Request, Response
from fastapi.responses import JSONResponse

from .. import logs, services
from ..channels.kiosk import controls
from ..channels.kiosk.controls import Control
from ..channels.kiosk.screen_controls_of import controls_piece
from ..channels.kiosk.glance import glance
from ..channels.model import Device, Inbound
from ..live.events import DeviceViewer
from ..workshop.workshop import ScreenNotFound, Workshop, WorkshopUnavailable
from . import chat
from .chat_models import KioskMessage
from .live import EventStream, stream_to
from .kiosk_device import Kiosk, counted, device_for, pair, same_site_write
from .kiosk_layout_models import KioskLayout, KioskPiece
from .models import (ChatConversation, ChatReply, ChatRequest, ErrorResponse, KioskControl, KioskControlDone,
                     KioskControls, KioskDevice, KioskGlance, KioskPairRequest)
from .live_models import LiveEvent

router = APIRouter()
log = logging.getLogger("ashley.api.kiosk")
_PAIRED: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "`unauthorized`: not paired, a revoked device, or from the public "
          "internet"},
    503: {"model": ErrorResponse, "description": "`unavailable`: a system it needs could not be reached"}}
_WRITE: dict[int | str, dict[str, Any]] = {
    **_PAIRED, 403: {"model": ErrorResponse, "description": "`forbidden`: from another site, or not JSON"}}
_ACTS: dict[int | str, dict[str, Any]] = {
    **_WRITE, 429: {"model": ErrorResponse, "description": "`rate_limited`: the device is over its rate"}}


def thread_of(device: Device) -> str:
    return f"device:{device.id}"


def inbound_from(device: Device, body: ChatRequest) -> Inbound:
    """The message as the turn loop takes it: the device's thread, kind, audience and place; shared, in text; tagged
    `said_aloud` when it is a `KioskMessage` that says so."""
    return Inbound(household_id=device.household_id, thread=thread_of(device), text=body.text, kind=device.kind,
                   medium="text", audience=device.audience, speaker_id=None, shared=True, place=device.place,
                   channel="web", remembers=device.remembers, later=True, later_by="turn",
                   device_id=device.id, taint=None, said_aloud=isinstance(body, KioskMessage) and body.said_aloud)


def _unavailable() -> JSONResponse:
    return JSONResponse(status_code=503, content=ErrorResponse(
        code="unavailable", detail="the controls are unavailable right now; try again shortly").model_dump())


def _device(device: Device) -> KioskDevice:
    return KioskDevice(id=device.id, name=device.name, place=device.place)


@router.post("/api/kiosk/session", response_model=KioskDevice, responses={
    **_WRITE, 422: {"model": ErrorResponse, "description": "a body outside `KioskPairRequest` gets FastAPI's own "
                    "validation error, which is not this schema"}})
async def kiosk_pair(request: Request, response: Response, body: KioskPairRequest,
                     _: Annotated[None, Depends(same_site_write)]) -> KioskDevice:
    """200 `KioskDevice`, and the kiosk cookie set; 401 `unauthorized` for a token that signs in no device or a request
    from the public internet; 403 `forbidden`; 422 FastAPI's validation error; 503 `unavailable`."""
    device = await device_for(request, body.token)
    pair(response, body.token)
    logs.info(log, "kiosk.paired", device=device.id)
    return _device(device)


@router.get("/api/kiosk/device", response_model=KioskDevice, responses=_PAIRED)
async def kiosk_device(device: Kiosk) -> KioskDevice:
    """200 `KioskDevice`; 401 `unauthorized`, which the page answers with its pairing form; 503 `unavailable`."""
    return _device(device)


@router.get("/api/kiosk/conversation", response_model=ChatConversation, responses=_PAIRED)
async def kiosk_conversation(device: Kiosk, request: Request) -> ChatConversation | JSONResponse:
    """200 `ChatConversation`, the open one on the device's thread; 401 `unauthorized`; 503 `unavailable`."""
    return await chat.conversation_on(device.household_id, thread_of(device), request)


@router.post("/api/kiosk/messages", response_model=ChatReply, responses={
    **_ACTS, 422: {"model": ErrorResponse, "description": "`refused`; a body outside `KioskMessage` gets FastAPI's "
                   "own validation error instead, which is not this schema"}})
async def kiosk_send(device: Kiosk, body: KioskMessage) -> ChatReply | JSONResponse:
    """200 `ChatReply` (`follows` false); 401 `unauthorized`; 403 `forbidden`; 422 `refused`, or FastAPI's validation
    error; 429 `rate_limited`; 503 `unavailable`."""
    await counted(device)
    return await chat.answer(inbound_from(device, body))


@router.get("/api/kiosk/live", response_class=EventStream, response_model=None, responses={
    **_PAIRED, 200: {"model": LiveEvent, "description": "A stream of `LiveEvent`, one per `data:` line",
                     "content": {"text/event-stream": {"schema": {"$ref": "#/components/schemas/LiveEvent"}}}}})
async def kiosk_live(device: Kiosk) -> Response:
    """200 a stream of `LiveEvent` for the device; 401 `unauthorized`; 503 `unavailable`: no live feed, so the page
    reads for itself."""
    return stream_to(DeviceViewer(device.household_id, device.id), device=device.id)


@router.get("/api/kiosk/glance", response_model=KioskGlance, responses=_PAIRED)
async def kiosk_glance(device: Kiosk) -> KioskGlance:
    """200 `KioskGlance`; 401 `unauthorized`; 503 `unavailable`."""
    seen = await glance(device.household_id)
    return KioskGlance(home=None if seen.home is None else list(seen.home), not_connected=["calendar", "reminders"],
                       locale=seen.locale, clock=seen.clock)


@router.get("/api/kiosk/layout", response_model=KioskLayout, responses=_PAIRED)
async def kiosk_layout(device: Kiosk) -> KioskLayout | JSONResponse:
    """200 `KioskLayout`, the device's screen as she has laid it out, read now; 401 `unauthorized`; 503 `unavailable`.
    Not counted against the device's rate."""
    try:
        view = await services.get(Workshop).screen(device.household_id, device.id)
    except ScreenNotFound:
        return _unpaired()
    except WorkshopUnavailable:
        return _unavailable()
    return KioskLayout(laid_out=view.laid_out, seq=view.seq, placed=[
        KioskPiece(id=p.id, kind=p.kind, order=p.place.order, size=p.place.size) for p in view.pieces])


async def _controls_of(device: Device) -> tuple[Control, ...] | JSONResponse:
    """The buttons of the device's screen, read now: none when it has no controls piece. 401 as `kiosk_layout`, 503."""
    try:
        piece = controls_piece(await services.get(Workshop).screen(device.household_id, device.id))
    except ScreenNotFound:
        return _unpaired()
    except WorkshopUnavailable:
        return _unavailable()
    return () if piece is None else piece[2]


def _unpaired() -> JSONResponse:
    return JSONResponse(status_code=401, content=ErrorResponse(
        code="unauthorized", detail="pair this screen with a device token").model_dump())


@router.get("/api/kiosk/controls", response_model=KioskControls, responses=_PAIRED)
async def kiosk_controls(device: Kiosk) -> KioskControls | JSONResponse:
    """200 `KioskControls`, the buttons of the device's screen's controls piece, read now; 401 `unauthorized`; 503
    `unavailable`."""
    found = await _controls_of(device)
    if isinstance(found, JSONResponse):
        return found
    return KioskControls(controls=[KioskControl(name=c.id, label=c.label) for c in found])


@router.post("/api/kiosk/controls/{name}", response_model=KioskControlDone, responses={
    **_ACTS, 404: {"model": ErrorResponse, "description": "`not_found`: no control has that name"},
    422: {"model": ErrorResponse, "description": "a name outside `[a-z0-9-]{1,40}` gets FastAPI's own validation "
          "error, which is not this schema"}})
async def kiosk_control(device: Kiosk,
                        name: Annotated[str, Path(pattern=r"^[a-z0-9-]{1,40}$")]) -> KioskControlDone | JSONResponse:
    """200 `KioskControlDone`; 401 `unauthorized`; 403 `forbidden`; 404 `not_found`; 422 FastAPI's validation error;
    429 `rate_limited`; 503 `unavailable`."""
    listed = await _controls_of(device)
    if isinstance(listed, JSONResponse):
        return listed
    found = next((c for c in listed if c.id == name), None)
    if found is None:
        return JSONResponse(status_code=404, content=ErrorResponse(code="not_found", detail="no such control")
                            .model_dump())
    await counted(device)
    return KioskControlDone(done=await controls.run(found, device.id, device.household_id))
