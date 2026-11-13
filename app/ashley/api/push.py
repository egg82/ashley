"""A signed-in person's notifications on this device (`decisions.md`, "Web push"). `GET /api/push/key` answers her
VAPID public key, which a browser subscribes with; `POST /api/push/subscriptions` keeps this browser's subscription for
the person; `POST /api/push/subscriptions/find` says whether this browser is theirs (a POST, so the endpoint, a secret,
never sits in a URL); `DELETE /api/push/subscriptions` stops pushing to it. With push not configured every route
answers 503.

Logs `push.subscribed` and `push.unsubscribed` with the person and how many browsers they have; never an endpoint or
key."""

import logging
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from .. import logs, services
from ..channels.push.config import identity
from ..channels.push.subscriptions import Browser, Subscriptions, SubscriptionsUnavailable
from .models import ErrorResponse, PushEndpointRequest, PushKeyResponse, PushStateResponse, PushSubscriptionRequest
from .person import Person

router = APIRouter()
log = logging.getLogger("ashley.api")
_SIGNED_IN: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "`unauthorized`: no live session"},
    503: {"model": ErrorResponse, "description": "`unavailable`: push is not set up here, or the database could not "
          "be reached"}}
_WRITE: dict[int | str, dict[str, Any]] = {
    **_SIGNED_IN,
    403: {"model": ErrorResponse, "description": "`forbidden`: the request came from another site or was not JSON"},
    422: {"model": ErrorResponse, "description": "an endpoint that is not a browser push service, or a body outside "
          "the request model, gets FastAPI's own validation error, which is not this schema"}}


def _unavailable() -> JSONResponse:
    return JSONResponse(status_code=503, content=ErrorResponse(
        code="unavailable", detail="notifications are unavailable right now").model_dump())


@router.get("/api/push/key", response_model=PushKeyResponse, responses=_SIGNED_IN)
async def get_push_key(request: Request, signed_in: Person) -> PushKeyResponse | JSONResponse:
    """200 `PushKeyResponse`; 401 `unauthorized`; 503 `unavailable` when push is not set up here."""
    found = identity(request.app.state.settings.vapid_subject)
    return _unavailable() if found is None else PushKeyResponse(public_key=found.public_key)


@router.post("/api/push/subscriptions", status_code=201, response_model=PushStateResponse, responses=_WRITE)
async def subscribe_push(body: PushSubscriptionRequest, signed_in: Person) -> PushStateResponse | JSONResponse:
    """201 `PushStateResponse`, this browser now the person's (moved from whoever had it); 401; 403; 422; 503."""
    person = signed_in.person
    subscriptions = services.get(Subscriptions)
    try:
        await subscriptions.add(person.household_id, person.id, Browser(body.endpoint, body.keys.p256dh,
                                                                        body.keys.auth))
        count, here = await subscriptions.count(person.id, body.endpoint)
    except SubscriptionsUnavailable:
        return _unavailable()
    logs.info(log, "push.subscribed", person=person.id, subscriptions=count)
    return PushStateResponse(subscriptions=count, this_browser=here)


@router.post("/api/push/subscriptions/find", response_model=PushStateResponse, responses=_WRITE)
async def find_push_subscription(body: PushEndpointRequest, signed_in: Person) -> PushStateResponse | JSONResponse:
    """200 `PushStateResponse`; changes nothing. 401; 403; 422; 503."""
    try:
        count, here = await services.get(Subscriptions).count(signed_in.person.id, body.endpoint)
    except SubscriptionsUnavailable:
        return _unavailable()
    return PushStateResponse(subscriptions=count, this_browser=here)


@router.delete("/api/push/subscriptions", response_model=PushStateResponse, responses=_WRITE)
async def unsubscribe_push(body: PushEndpointRequest, signed_in: Person) -> PushStateResponse | JSONResponse:
    """200 `PushStateResponse`, this browser no longer the person's; an endpoint that was not theirs changes nothing.
    401; 403; 422; 503."""
    person = signed_in.person
    subscriptions = services.get(Subscriptions)
    try:
        await subscriptions.remove(person.id, body.endpoint)
        count, here = await subscriptions.count(person.id, body.endpoint)
    except SubscriptionsUnavailable:
        return _unavailable()
    logs.info(log, "push.unsubscribed", person=person.id, subscriptions=count)
    return PushStateResponse(subscriptions=count, this_browser=here)
