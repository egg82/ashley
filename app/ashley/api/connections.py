"""The signed-in person's household's connections (`decisions.md`, "A household connects its own services"). Any
person of the household may see, add, replace, rename and remove them.

`GET /api/connections` lists them with every kind that can be connected (the registered `ConnectionKind`s, which the
panel draws from). `POST /api/connections` adds one of a kind under a label and `PUT /api/connections/{id}` replaces
its address and key or token: the key or token is checked against the service first, by the kind's own authenticated
read, and nothing is stored when that fails (400 `ConnectionRefused`, in the kind's own words). `PATCH` renames it or
hands it to the household or takes it back (`connection_holders`), and `DELETE` removes it. A connection a person holds
(a code host, a Google account) is theirs, listed only to them and read only when they speak, until they hand it over. A connection is addressed by its id; one the signed-in person cannot see is 404, as a name no adapter
registered is. A label an owner already uses for the kind is 409 `label_taken`, and an owner at the kind's `most` is
409 `too_many`.

One log line per list, connect, refusal, rename and removal, with household and person ids, the kind, the connection id
and the outcome; never the key, the token, the address or the label."""

import logging
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks
from fastapi.responses import JSONResponse, Response

from .. import logs, services
from ..connections.connections import Connections, ConnectionsUnavailable, LabelTaken, TooMany
from ..connections.kinds import BridgeLogin, ConnectionKind, ConnectionKinds, OAuth, Pasted, Refusal
from ..connections.model import Connection, Resource
from ..connections.oauth import OAuthProviders
from ..connections.resources import ConnectionResources
from ..people.people import People, PeopleUnavailable
from . import connection_holders
from .connection_models import (ApiKeyConnectionRequest, ConnectionChange, ConnectionKindInfo, ConnectionRefused,
                                ConnectionRequest, ConnectionsResponse, HouseholdConnection, NewConnectionRequest)
from .models import ErrorResponse, Person as WirePerson
from .person import Person

router = APIRouter()
log = logging.getLogger("ashley.api")
_READ: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "`unauthorized`: no live session"},
    503: {"model": ErrorResponse, "description": "`unavailable`: the database could not be reached, or connections "
          "are not set up here"}}
_WRITE: dict[int | str, dict[str, Any]] = {
    **_READ, 403: {"model": ErrorResponse, "description": "`forbidden`: the request came from another site"}}
_PUT: dict[int | str, dict[str, Any]] = {
    **_WRITE, 400: {"model": ConnectionRefused, "description": "the service did not answer with that address and "
                    "key or token, or the address is not one; nothing was stored"},
    422: {"model": ErrorResponse, "description": "a body outside the request's schema gets FastAPI's own validation "
          "error, which is not this schema"}}


_INVALID = {422: {"model": ErrorResponse, "description": "a body or id outside the request's schema gets FastAPI's own "
                  "validation error, which is not this schema"}}
_NOT_FOUND = {404: {"model": ErrorResponse, "description": "`not_found`: no such connection, or none the signed-in "
                    "person can see; for a new one, no such kind"}}
_CONFLICT = {409: {"model": ErrorResponse, "description": "`label_taken`: the owner has a connection of that kind "
                   "under that label; `too_many`: the owner holds as many of that kind as it allows"}}


def _unavailable() -> JSONResponse:
    return JSONResponse(status_code=503, content=ErrorResponse(
        code="unavailable", detail="connections are unavailable right now; try again shortly").model_dump())


def _not_found(detail: str = "there is no such connection") -> JSONResponse:
    return JSONResponse(status_code=404, content=ErrorResponse(code="not_found", detail=detail).model_dump())


def _conflict(e: LabelTaken | TooMany) -> JSONResponse:
    if isinstance(e, LabelTaken):
        body = ErrorResponse(code="label_taken", detail="you already have one of those under that name")
    else:
        body = ErrorResponse(code="too_many", detail="you already have as many of those as can be connected")
    return JSONResponse(status_code=409, content=body.model_dump())


def _refused(kind: ConnectionKind, reason: Refusal, household: int, person: int) -> JSONResponse:
    logs.info(log, "connections.refused", household=household, person=person, kind=kind.name, reason=reason)
    return JSONResponse(status_code=400, content=ConnectionRefused(reason=reason,
                                                                   detail=kind.refusals[reason]).model_dump())


def _connect_of(kind: ConnectionKind) -> Literal["pasted", "oauth", "bridge"]:
    if isinstance(kind.connect, OAuth):
        return "oauth"
    return "bridge" if isinstance(kind.connect, BridgeLogin) else "pasted"


def _kinds() -> list[ConnectionKindInfo]:
    return [ConnectionKindInfo(
        name=k.name, title=k.title, what=k.what, blurb=k.blurb, connected=k.connected, removed=k.removed,
        holders=sorted(k.holders), most=k.most, takes_address=k.fixed_address is None,
        address_placeholder=k.address_placeholder, secret_field=k.secret_field, secret_label=k.secret_label,
        secret_noun=k.secret_noun, connect=_connect_of(k), has_settings=bool(k.settings),
        set_up=not isinstance(k.connect, OAuth) or services.get(OAuthProviders).get(k.connect.provider) is not None)
        for k in services.get(ConnectionKinds).all()]


async def _people(household_id: int) -> dict[int, WirePerson]:
    found = await services.get(People).household(household_id)
    return {} if found is None else {
        p.id: WirePerson(id=p.id, household_id=p.household_id, name=p.name) for p in found.people}


def _missing_scopes(c: Connection) -> list[str]:
    kind = services.get(ConnectionKinds).get(c.kind)
    if kind is None or not isinstance(kind.connect, OAuth):
        return []
    return kind.connect.missing(c.scopes)


def _wire(c: Connection, people: dict[int, WirePerson], me: int,
          resources: tuple[Resource, ...] = ()) -> HouseholdConnection:
    added_by = people.get(c.added_by) if c.added_by is not None else None
    kind = services.get(ConnectionKinds).get(c.kind)
    holders: frozenset[str] = frozenset() if kind is None else kind.holders
    return HouseholdConnection(id=c.id, label=c.label, kind=c.kind, base_url=c.base_url, added_by=added_by,
                               added_at=c.added_at, checked_at=c.checked_at, personal=c.person_id is not None,
                               needs=c.needs, scopes=list(c.scopes), missing_scopes=_missing_scopes(c),
                               resources=[connection_holders.wire_resource(r) for r in resources],
                               can_hand_over=c.person_id == me and "household" in holders,
                               can_take_back=c.person_id is None and c.added_by == me and "person" in holders)


def _secret(body: ConnectionRequest | NewConnectionRequest, kind: ConnectionKind) -> str | JSONResponse:
    """The body's secret, or the 422 `unsupported` when it carries the other field than the kind's, or the kind is
    connected through its service's own consent screen (`ashley.api.connection_oauth`) and has no secret to paste."""
    if not isinstance(kind.connect, Pasted):
        return JSONResponse(status_code=422, content=ErrorResponse(
            code="unsupported", detail=f"{kind.title} is connected through its own sign-in").model_dump())
    field, secret = ("api_key", body.api_key) if isinstance(body, ApiKeyConnectionRequest) else ("token", body.token)
    if field != kind.secret_field:
        return JSONResponse(status_code=422, content=ErrorResponse(
            code="unsupported", detail=f"{kind.title} takes its secret as `{kind.secret_field}`").model_dump())
    return secret


async def _checked(signed_in: Person, kind: ConnectionKind, typed: str | None, secret: str) -> str | JSONResponse:
    """The address to store, once the kind's own read answers with it and the secret; else the 400 or 503."""
    person = signed_in.person
    if not services.get(Connections).can_open():
        return _unavailable()
    base = kind.base_url(typed)
    if base is None:
        return _refused(kind, "bad_url", person.household_id, person.id)
    refusal = await kind.check(base, secret, person.id)
    if refusal is not None:
        return _refused(kind, refusal, person.household_id, person.id)
    return base


@router.get("/api/connections", response_model=ConnectionsResponse, responses=_READ)
async def list_connections(signed_in: Person, after: BackgroundTasks) -> ConnectionsResponse | JSONResponse:
    """200 `ConnectionsResponse`, from stored rows only; 401 `unauthorized`; 503 `unavailable` (the database). What each
    connection reaches is read from its service after the answer is sent, so the next opening shows it."""
    household = signed_in.person.household_id
    connections = services.get(Connections)
    if not connections.can_open():
        return ConnectionsResponse(connections=[], offered=_kinds(), can_connect=False)
    me = signed_in.person.id
    try:
        found = await connections.of_household(household, me)
        people, resources = await _people(household), await services.get(ConnectionResources).of_household(household, me)
    except (ConnectionsUnavailable, PeopleUnavailable):
        return _unavailable()
    after.add_task(connection_holders.refreshed, household, me, found)
    logs.info(log, "connections.listed", household=household, count=len(found))
    return ConnectionsResponse(connections=[_wire(c, people, me, resources.get(c.id, ())) for c in found],
                               offered=_kinds(), can_connect=True)


@router.post("/api/connections", status_code=201, response_model=HouseholdConnection, responses={
    **_PUT, **_NOT_FOUND, **_CONFLICT})
async def connect(signed_in: Person, body: NewConnectionRequest) -> HouseholdConnection | JSONResponse:
    """201 `HouseholdConnection`, added (a personal kind as the signed-in person's own); 400 `ConnectionRefused`;
    401 `unauthorized`; 403 `forbidden`; 404 `not_found`, no such kind; 409 `label_taken` or `too_many`; 422
    `unsupported`, the body carries the other secret field than the kind's; 503 `unavailable`, also when connections
    are not set up here."""
    person = signed_in.person
    registered = services.get(ConnectionKinds).get(body.kind)
    if registered is None:
        return _not_found("there is no such kind of connection")
    secret = _secret(body, registered)
    if isinstance(secret, JSONResponse):
        return secret
    base = await _checked(signed_in, registered, body.base_url, secret)
    if isinstance(base, JSONResponse):
        return base
    try:
        connection = await services.get(Connections).add(person.household_id, registered.name, body.label, base,
                                                         secret, person.id)
        await connection_holders.stored(connection.id, person.household_id, person.id)
        shown = await _shown(signed_in, connection)
    except (LabelTaken, TooMany) as e:
        return _conflict(e)
    except (ConnectionsUnavailable, PeopleUnavailable):
        return _unavailable()
    logs.info(log, "connections.connected", household=person.household_id, person=person.id, kind=registered.name,
              connection=connection.id)
    return shown


async def _visible(signed_in: Person, connection_id: int) -> Connection | None:
    person = signed_in.person
    found = await services.get(Connections).of_household(person.household_id, person.id)
    return next((c for c in found if c.id == connection_id), None)


@router.put("/api/connections/{connection_id}", response_model=HouseholdConnection, responses={
    **_PUT, **_NOT_FOUND})
async def replace(signed_in: Person, connection_id: int, body: ConnectionRequest) -> HouseholdConnection | JSONResponse:
    """200 `HouseholdConnection`, with its new address and key or token; 400 `ConnectionRefused`; 401 `unauthorized`;
    403 `forbidden`; 404 `not_found`; 422 `unsupported`; 503 `unavailable`."""
    person = signed_in.person
    try:
        held = await _visible(signed_in, connection_id)
    except ConnectionsUnavailable:
        return _unavailable()
    registered = None if held is None else services.get(ConnectionKinds).get(held.kind)
    if held is None or registered is None:
        return _not_found()
    secret = _secret(body, registered)
    if isinstance(secret, JSONResponse):
        return secret
    base = await _checked(signed_in, registered, body.base_url, secret)
    if isinstance(base, JSONResponse):
        return base
    try:
        connection = await services.get(Connections).replace(connection_id, person.household_id, person.id, base,
                                                             secret)
        if connection is not None:
            await connection_holders.stored(connection_id, person.household_id, person.id)
        shown = None if connection is None else await _shown(signed_in, connection)
    except (ConnectionsUnavailable, PeopleUnavailable):
        return _unavailable()
    if shown is None:
        return _not_found()
    logs.info(log, "connections.connected", household=person.household_id, person=person.id, kind=held.kind,
              connection=connection_id)
    return shown


async def _shown(signed_in: Person, connection: Connection) -> HouseholdConnection:
    """The connection as the signed-in person sees it, with what it reaches. Raises ConnectionsUnavailable,
    PeopleUnavailable."""
    person = signed_in.person
    people = await _people(person.household_id)
    resources = await services.get(ConnectionResources).of_household(person.household_id, person.id)
    return _wire(connection, people, person.id, resources.get(connection.id, ()))


@router.patch("/api/connections/{connection_id}", response_model=HouseholdConnection, responses={
    **_WRITE, **_INVALID, **_NOT_FOUND, **_CONFLICT})
async def change(signed_in: Person, connection_id: int, body: ConnectionChange) -> HouseholdConnection | JSONResponse:
    """200 `HouseholdConnection`, under its new label or held by its new holder (`connection_holders`); 401
    `unauthorized`; 403 `forbidden`, for taking back one the signed-in person did not add; 404 `not_found`; 409
    `label_taken` or `too_many`; 422 `unsupported`, a holder the kind does not allow; 503 `unavailable`."""
    person = signed_in.person
    try:
        if body.holder is not None:
            changed = await connection_holders.moved(signed_in, connection_id, body.holder)
            return changed if isinstance(changed, JSONResponse) else await _shown(signed_in, changed)
        connection = await services.get(Connections).relabel(connection_id, person.household_id, person.id,
                                                             body.label or "")
        shown = None if connection is None else await _shown(signed_in, connection)
    except LabelTaken as e:
        return _conflict(e)
    except (ConnectionsUnavailable, PeopleUnavailable):
        return _unavailable()
    if shown is None:
        return _not_found()
    logs.info(log, "connections.renamed", household=person.household_id, person=person.id, kind=shown.kind,
              connection=connection_id)
    return shown


@router.delete("/api/connections/{connection_id}", status_code=204, response_class=Response, responses={
    **_WRITE, **_INVALID, **_NOT_FOUND})
async def disconnect(signed_in: Person, connection_id: int) -> Response:
    """204, removed; 401 `unauthorized`; 403 `forbidden`; 404 `not_found`; 503 `unavailable`."""
    person = signed_in.person
    try:
        held = await _visible(signed_in, connection_id)
        gone = held is not None and await services.get(Connections).remove(connection_id, person.household_id,
                                                                           person.id)
    except ConnectionsUnavailable:
        return _unavailable()
    if held is None or not gone:
        return _not_found()
    logs.info(log, "connections.disconnected", household=person.household_id, person=person.id, kind=held.kind,
              connection=connection_id)
    return Response(status_code=204)
