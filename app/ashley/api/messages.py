"""The first channel adapter: a signed-in device sends what was said and gets her reply back in the response, rendered
for the device's medium. The device signs in with `Authorization: Bearer <token>` (`Devices.by_token`); a missing,
malformed or unknown token is 401 before any data is read, and the body is never logged.

A device token works only from the LAN and the clusters. Public traffic arrives only through the Cloudflare tunnel,
whose edge sets `Cf-Connecting-IP` on every request it forwards (a client cannot send it past the edge), while LAN
clients reach the app through the gateway, which never sets it. So a request carrying that header is a public one and
its device token is refused with 401; a LAN client that adds the header only locks itself out. Each refusal is one
`api.device_refused` line with the device id and the reason (`public` or `rate`), never the token. A device over its
rate (`device_rate.json`, counted in Postgres by `Devices.allow`) gets 429 `rate_limited`. A body that is not JSON at
all is FastAPI's 422 first, since it parses JSON before any dependency runs; that reads nothing either.

The thread is `device:<id>`, or `device:<id>:<thread>` when the body names one, so one device can hold several
conversations at once (the eval harness running probes side by side). A device is `shared`, its speaker found by
presence."""

import logging
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .. import logs, services
from ..channels.devices import Devices, DevicesUnavailable
from ..channels.model import Device, Inbound
from ..channels.respond import RespondRefused, RespondUnavailable, respond
from .models import ErrorResponse, MessageRequest, MessageResponse
from .receipt_models import wire_receipts

router = APIRouter()
log = logging.getLogger("ashley.api.messages")
_TRY_AGAIN = "she cannot answer right now; try again shortly"
_bearer = HTTPBearer(auto_error=False, description="A device token from `python -m ashley.channels.devices add`.")


class Unauthorized(Exception):
    """No device signed in; `main` answers it with 401 `unauthorized`."""

    detail = "sign in with a device token"


class PublicRequest(Unauthorized):
    """A device token arrived from the public internet, where it is not accepted."""

    detail = "device tokens work only on the home network"


class RateLimited(Exception):
    """The device is over its rate; `main` answers it with 429 `rate_limited`."""


class Unavailable(Exception):
    """The device could not be signed in for want of the database; `main` answers it with 503 `unavailable`."""


async def unauthorized(_: Request, exc: Exception) -> JSONResponse:
    detail = exc.detail if isinstance(exc, Unauthorized) else Unauthorized.detail
    return _error(401, "unauthorized", detail, {"WWW-Authenticate": "Bearer"})


async def rate_limited(_: Request, __: Exception) -> JSONResponse:
    return _error(429, "rate_limited", "too many requests; slow down")


async def unavailable(_: Request, __: Exception) -> JSONResponse:
    return _error(503, "unavailable", _TRY_AGAIN)


async def signed_in(request: Request,
                    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]) -> Device:
    """The device the bearer token signs in. Runs before the body is validated, so a bad token is 401 first, then a
    public request is 401 and a device over its rate is 429."""
    if credentials is None:
        raise Unauthorized()
    try:
        device = await services.get(Devices).by_token(credentials.credentials)
        if device is None:
            raise Unauthorized()
        if "cf-connecting-ip" in request.headers:
            logs.info(log, "api.device_refused", device=device.id, reason="public")
            raise PublicRequest()
        if not await services.get(Devices).allow(device.id):
            logs.info(log, "api.device_refused", device=device.id, reason="rate")
            raise RateLimited()
    except DevicesUnavailable as e:
        raise Unavailable() from e
    return device


@router.post("/api/messages", response_model=MessageResponse, response_model_exclude_unset=True, responses={
    401: {"model": ErrorResponse, "description": "`unauthorized`; also a device token sent from the public internet"},
    422: {"model": ErrorResponse, "description": "`refused`; a body outside `MessageRequest` gets FastAPI's own "
          "validation error instead, which is not this schema"},
    429: {"model": ErrorResponse, "description": "`rate_limited`; the device is over its rate"},
    503: {"model": ErrorResponse},
})
async def post_message(device: Annotated[Device, Depends(signed_in)],
                       body: MessageRequest) -> MessageResponse | JSONResponse:
    """200 `MessageResponse`; 401 `unauthorized`; 429 `rate_limited`; 422 FastAPI's validation error for a body outside `MessageRequest`;
    422 `refused` when the model declined; 503 `unavailable` when a system the reply needs could not be reached
    (`RespondUnavailable`, `DevicesUnavailable`)."""
    try:
        out = await respond(inbound_from(device, body))
    except RespondRefused:
        return _error(422, "refused", "she declined to answer that")
    except RespondUnavailable:
        return _error(503, "unavailable", _TRY_AGAIN)
    shown = {} if out.receipts is None else {"receipts": wire_receipts(out.receipts)}
    return MessageResponse(conversation_id=out.conversation_id, medium=out.medium, body=out.body, **shown)


def inbound_from(device: Device, body: MessageRequest) -> Inbound:
    """The message as the turn loop takes it: the device's thread, place, audience, medium and kind; shared, so presence
    names the speaker."""
    thread = f"device:{device.id}" if body.thread is None else f"device:{device.id}:{body.thread}"
    return Inbound(household_id=device.household_id, thread=thread, text=body.text, kind=device.kind,
                   medium=device.medium, audience=device.audience, speaker_id=None, shared=True, place=device.place,
                   channel="device", remembers=device.remembers, taint=None)


def _error(status: int, code: Literal["unauthorized", "refused", "unavailable", "rate_limited"], detail: str, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse(status_code=status, content=ErrorResponse(code=code, detail=detail).model_dump(), headers=headers)
