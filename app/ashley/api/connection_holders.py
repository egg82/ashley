"""Who holds a connection and what it reaches (`decisions.md`, "Who holds a connection, and who sees what it reaches"):
handing a connection to the household or taking it back (`PATCH /api/connections/{id}` with `holder`), sharing or keeping
one of its resources (`PATCH /api/connections/{id}/resources/{ref}`), and reading what each connection reaches when the
room is opened.

A take-back by anyone but the person who added the connection is 403 `forbidden`; a holder its kind does not allow is
422 `unsupported`; a new holder that has one of the kind under that label is 409 `label_taken` and one at the kind's
`most` is 409 `too_many`, nothing moved for either. Keeping a household connection's resource is 409
`held_by_household`. One log line per move and share, with ids and the outcome."""

import asyncio
import logging
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from .. import logs, services
from ..connections.connections import Connections, ConnectionsUnavailable, LabelTaken, NotAdder, TooMany
from ..connections.kinds import ConnectionKinds
from ..connections.model import Connection, Holder, Resource
from ..connections.resource_sync import sync
from ..connections.resources import ConnectionResources, HeldByHousehold
from .connection_models import ConnectionResource, ResourceShare
from .models import ErrorResponse
from .person import Person

router = APIRouter()
log = logging.getLogger("ashley.api")
_SHARE: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "`unauthorized`: no live session"},
    403: {"model": ErrorResponse, "description": "`forbidden`: the request came from another site"},
    404: {"model": ErrorResponse, "description": "`not_found`: no such connection or resource, or none the signed-in "
          "person can see (a person's own connection is visible to its owner alone)"},
    409: {"model": ErrorResponse, "description": "`held_by_household`: a household connection's resources are all "
          "shared"},
    422: {"model": ErrorResponse, "description": "a body or id outside the request's schema gets FastAPI's own "
          "validation error, which is not this schema"},
    503: {"model": ErrorResponse, "description": "`unavailable`: the database could not be reached, or connections "
          "are not set up here"}}


def wire_resource(r: Resource) -> ConnectionResource:
    return ConnectionResource(ref=r.ref, kind=r.kind, name=r.name, shared=r.shared)


def _error(status: int, code: str, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"code": code, "detail": detail})


async def moved(signed_in: Person, connection_id: int, holder: Holder) -> Connection | JSONResponse:
    """The connection after `holder` holds it, or the response that says why not (404 included)."""
    person = signed_in.person
    try:
        found = await services.get(Connections).move(connection_id, person.household_id, person.id, holder)
    except NotAdder:
        return _error(403, "forbidden", "only the person who added it can take it back")
    except ValueError:
        return _error(422, "unsupported", "that kind of connection cannot be held that way")
    except LabelTaken:
        return _error(409, "label_taken", "the new holder already has one of those under that name; rename it first")
    except TooMany:
        return _error(409, "too_many", "the new holder already has as many of those as can be connected")
    except ConnectionsUnavailable:
        return _error(503, "unavailable", "connections are unavailable right now; try again shortly")
    if found is None:
        return _error(404, "not_found", "there is no such connection")
    return found


async def stored(connection_id: int, household_id: int, person_id: int) -> None:
    """Store what a connection just stored or replaced reaches; a service that does not say leaves it to the next
    opening of the room."""
    try:
        opened = await services.get(Connections).opened(connection_id, household_id, person_id)
        if opened is not None:
            await sync(opened)
    except ConnectionsUnavailable:
        logs.warning(log, "connections.resources_unread", household=household_id, count=1)


async def refreshed(household_id: int, person_id: int, found: tuple[Connection, ...]) -> None:
    """Read what each connection of a kind that lists resources reaches, and store it. A connection the service could
    not answer for keeps what it had."""
    kinds = [c for c in found if _lists(c)]

    async def one(connection: Connection) -> None:
        opened = await services.get(Connections).opened(connection.id, household_id, person_id)
        if opened is not None:
            await sync(opened)

    done = await asyncio.gather(*(one(c) for c in kinds), return_exceptions=True)
    failed = sum(isinstance(d, BaseException) for d in done)
    if failed:
        logs.warning(log, "connections.resources_unread", household=household_id, count=failed)


def _lists(connection: Connection) -> bool:
    kind = services.get(ConnectionKinds).get(connection.kind)
    return kind is not None and kind.resources is not None


@router.patch("/api/connections/{connection_id}/resources/{ref:path}", response_model=ConnectionResource,
              responses=_SHARE)
async def share(signed_in: Person, connection_id: int, ref: str, body: ResourceShare) -> ConnectionResource | JSONResponse:
    """200 `ConnectionResource`, shared with the household or kept; 401 `unauthorized`; 403 `forbidden`; 404
    `not_found`; 409 `held_by_household`; 503 `unavailable`."""
    person = signed_in.person
    try:
        found = await services.get(ConnectionResources).share(connection_id, person.household_id, person.id, ref,
                                                              body.shared)
    except HeldByHousehold:
        return _error(409, "held_by_household", "the household already holds this connection, so all of it is shared")
    except ConnectionsUnavailable:
        return _error(503, "unavailable", "connections are unavailable right now; try again shortly")
    if found is None:
        return _error(404, "not_found", "there is no such resource")
    return wire_resource(found)
