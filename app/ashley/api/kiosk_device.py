"""A kiosk browser signed in as a device: `kiosk_signed_in`, the dependency every kiosk route uses, as
`person.person_signed_in` is for a person. The tablet pairs once with a device token from the admin CLI; the token is
then kept in a `__Host-` cookie (Secure, Path=/, no Domain), HttpOnly and SameSite=Strict, and checked by
`Devices.by_token` on every request, so revoking the device unpairs the tablet and no table of kiosk sessions exists.
The cookie's value is never logged.

The two cookies never stand in for each other: a kiosk route reads only `KIOSK_COOKIE` and a person's route only the
session cookie, so a person signed in on the same browser is not the kiosk, nor the kiosk a person.

The device rule holds as for `POST /api/messages`: a request carrying `Cf-Connecting-IP` came through the public tunnel
and is refused with 401, logged as `api.device_refused` with the device id and `reason=public`. A write must come from
this site, as JSON (`person.same_site`). Only what makes her act counts against the device's rate (`counted`):
messages and controls. The page's reads (its conversation, the glance, the control list) poll at fixed, modest rates
and cost no tokens, so counting them would only let the page's own polling spend the budget meant for talking."""

import logging
from typing import Annotated

from fastapi import Depends, Request, Response
from fastapi.responses import JSONResponse

from .. import logs, services
from ..channels.devices import Devices, DevicesUnavailable
from ..channels.model import Device
from .messages import RateLimited, Unavailable
from .models import ErrorResponse
from .person import JSON, WAV, CrossSite, same_site

log = logging.getLogger("ashley.api.kiosk")

KIOSK_COOKIE = "__Host-ashley_kiosk"
_COOKIE_S = 400 * 24 * 3600   # browsers cap a cookie's life at 400 days; revoking the device ends it sooner
_READS = frozenset({"GET", "HEAD", "OPTIONS"})


class NotPaired(Exception):
    """No paired device; `main` answers it with 401 `unauthorized`."""

    detail = "pair this screen with a device token"


class PublicKiosk(NotPaired):
    """A kiosk request arrived from the public internet, where device tokens are not accepted."""

    detail = "device tokens work only on the home network"


async def not_paired(_: Request, exc: Exception) -> JSONResponse:
    detail = exc.detail if isinstance(exc, NotPaired) else NotPaired.detail
    return JSONResponse(status_code=401, content=ErrorResponse(code="unauthorized", detail=detail).model_dump())


async def device_for(request: Request, token: str) -> Device:
    """The device `token` signs in, from the home network. Raises NotPaired, PublicKiosk or Unavailable."""
    try:
        device = await services.get(Devices).by_token(token) if token else None
    except DevicesUnavailable as e:
        raise Unavailable() from e
    if device is None:
        raise NotPaired()
    if "cf-connecting-ip" in request.headers:
        logs.info(log, "api.device_refused", device=device.id, reason="public")
        raise PublicKiosk()
    return device


async def same_site_write(request: Request) -> None:
    """Refuse a write from another site, or not JSON, before FastAPI reads its body, so the refusal is 403 whatever
    the body is. Raises CrossSite."""
    _from_this_site(request, JSON)


def _from_this_site(request: Request, body_type: str) -> None:
    if request.method not in _READS and not same_site(request, body_type):
        logs.info(log, "signin.cross_site", method=request.method)
        raise CrossSite()


async def kiosk_signed_in(request: Request) -> Device:
    """The device this browser's kiosk cookie signs in. A write is checked for its site first, so a forged one reads
    nothing. Raises CrossSite, NotPaired, PublicKiosk or Unavailable."""
    await same_site_write(request)
    return await device_for(request, request.cookies.get(KIOSK_COOKIE, ""))


async def kiosk_speaking(request: Request) -> Device:
    """`kiosk_signed_in` for a write whose body is a WAV (`spoken`) rather than JSON."""
    _from_this_site(request, WAV)
    return await device_for(request, request.cookies.get(KIOSK_COOKIE, ""))


Kiosk = Annotated[Device, Depends(kiosk_signed_in)]
KioskSpeaking = Annotated[Device, Depends(kiosk_speaking)]


async def counted(device: Device) -> None:
    """Count one request that makes her act against the device's rate. Raises RateLimited or Unavailable."""
    try:
        allowed = await services.get(Devices).allow(device.id)
    except DevicesUnavailable as e:
        raise Unavailable() from e
    if not allowed:
        logs.info(log, "api.device_refused", device=device.id, reason="rate")
        raise RateLimited()


def pair(response: Response, token: str) -> None:
    response.set_cookie(KIOSK_COOKIE, token, max_age=_COOKIE_S, path="/", secure=True, httponly=True,
                        samesite="strict")
