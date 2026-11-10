"""What a person sets on a connection (`decisions.md`, "A connection has settings its person sets"). Any person of the
household may read and write them, from a signed-in session of this site: nothing else reaches `SettingsWriter`, so
what decides her trust (`ConnectionKind.settings` marked `taint` or `tier`) is never written by her own tools.

`GET /api/connections/{id}/settings` answers the settings with the schema the kind declares and a `revision`;
`PUT` replaces the whole of them and must carry the revision read, else 409 `version_conflict`; an unknown key, a value
of the wrong shape or an id that is not one is 422 `SettingsRefused`. `GET .../settings/history` lists the keys changed,
and `GET .../catalogue` what the connection's service has now for a setting to pick from. A connection of a kind with
no settings, or one the person cannot see, is 404.

One log line per write (the writer's `connections.settings.changed`: key names and a count, never the values) and one
per refusal."""

import logging
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from pydantic import StringConstraints

from .. import logs, services
from ..connections.connections import Connections, ConnectionsUnavailable
from ..connections.kinds import CatalogueUnavailable, ConnectionKind, ConnectionKinds
from ..connections.model import Catalogued, Connection
from ..connections.settings import (ActionList, EntityList, EntityListPerAction, Field, SettingsInvalid, SettingValue,
                                    SettingValues)
from ..connections.settings_read import SettingsReader, StoredSettings
from ..connections.settings_write import SettingsWriter, VersionConflict
from ..people.people import People, PeopleUnavailable
from .connection_settings_models import (ActionIds, ActionListField, CatalogueActionInfo, CatalogueEntityInfo,
                                         ConnectionCatalogue, ConnectionSettings, ConnectionSettingsRequest,
                                         EntityListField, EntityPerActionField, SettingChange, SettingChanges,
                                         SettingEntry, SettingField, SettingInfo, SettingsRefused)
from .models import ErrorResponse, Person as WirePerson
from .person import Person

router = APIRouter()
log = logging.getLogger("ashley.api")
_READ: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "`unauthorized`: no live session"},
    404: {"model": ErrorResponse, "description": "`not_found`: no such connection, or none the signed-in person can "
          "see, or its kind has no settings"},
    422: {"model": ErrorResponse, "description": "a parameter outside its bounds gets FastAPI's own validation error, "
          "which is not this schema"},
    503: {"model": ErrorResponse, "description": "`unavailable`: the database could not be reached, or the service "
          "did not answer"}}
_WRITE: dict[int | str, dict[str, Any]] = {
    **_READ, 403: {"model": ErrorResponse, "description": "`forbidden`: the request came from another site"},
    409: {"model": ErrorResponse, "description": "`version_conflict`: the settings changed since the version sent"},
    422: {"model": SettingsRefused, "description": "the settings are not ones the kind takes; nothing was stored. A "
          "body outside the request's schema gets FastAPI's own validation error, which is not this schema"}}
Domain = Annotated[str, StringConstraints(pattern=r"^[a-z0-9_]+$", max_length=64)]


def _error(status: int, code: Literal["not_found", "unavailable", "version_conflict"], detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content=ErrorResponse(code=code, detail=detail).model_dump())


def _not_found() -> JSONResponse:
    return _error(404, "not_found", "there is no such connection with settings")


def _unavailable() -> JSONResponse:
    return _error(503, "unavailable", "settings are unavailable right now; try again shortly")


async def _held(signed_in: Person, connection_id: int) -> tuple[Connection, ConnectionKind] | None:
    """The household's connection `connection_id` when the person sees it and its kind has settings. Raises
    ConnectionsUnavailable."""
    person = signed_in.person
    found = await services.get(Connections).of_household(person.household_id, person.id)
    held = next((c for c in found if c.id == connection_id and c.person_id is None), None)
    kind = None if held is None else services.get(ConnectionKinds).get(held.kind)
    return None if held is None or kind is None or not kind.settings else (held, kind)


def _field(field: Field) -> SettingField:
    if isinstance(field, EntityListPerAction):
        return EntityPerActionField(type="entity_per_action", for_actions=list(field.actions), domains=list(field.domains))
    if isinstance(field, EntityList):
        return EntityListField(type="entity_list", domains=list(field.domains))
    assert isinstance(field, ActionList)
    return ActionListField(type="action_list", domains=list(field.domains))


def _entries(values: dict[str, SettingValue]) -> list[SettingEntry]:
    return [SettingEntry(key=k, ids=v if isinstance(v, list) else [],
                         per_action=[] if isinstance(v, list) else [ActionIds(action=a, ids=i) for a, i in v.items()])
            for k, v in sorted(values.items())]


def _values(entries: list[SettingEntry]) -> SettingValues:
    """The request's entries as the stored shape. A key listed twice is refused by the writer's validation as the
    last one wins here, so the body says what it means."""
    return {e.key: ({a.action: a.ids for a in e.per_action} if e.per_action else e.ids) for e in entries}


async def _person(household_id: int, person_id: int | None) -> WirePerson | None:
    if person_id is None:
        return None
    found = await services.get(People).household(household_id)
    person = None if found is None else next((p for p in found.people if p.id == person_id), None)
    return None if person is None else WirePerson(id=person.id, household_id=person.household_id, name=person.name)


async def _wire(connection: Connection, kind: ConnectionKind, stored: StoredSettings) -> ConnectionSettings:
    return ConnectionSettings(
        connection_id=connection.id, kind=kind.name, revision=stored.version,
        settings=[SettingInfo(key=s.key, field=_field(s.field), decides=s.decides)
                  for s in kind.settings],
        values=_entries(stored.values), updated_at=stored.updated_at,
        updated_by=await _person(connection.household_id, stored.updated_by))


@router.get("/api/connections/{connection_id}/settings", response_model=ConnectionSettings, responses=_READ)
async def read_settings(signed_in: Person, connection_id: int) -> ConnectionSettings | JSONResponse:
    """200 `ConnectionSettings`; 401 `unauthorized`; 404 `not_found`; 503 `unavailable`."""
    try:
        held = await _held(signed_in, connection_id)
        if held is None:
            return _not_found()
        stored = await services.get(SettingsReader).stored(connection_id, signed_in.person.household_id)
        return await _wire(*held, stored)
    except (ConnectionsUnavailable, PeopleUnavailable):
        return _unavailable()


@router.put("/api/connections/{connection_id}/settings", response_model=ConnectionSettings, responses=_WRITE)
async def write_settings(signed_in: Person, connection_id: int,
                         body: ConnectionSettingsRequest) -> ConnectionSettings | JSONResponse:
    """200 `ConnectionSettings` as stored; 401 `unauthorized`; 403 `forbidden`; 404 `not_found`; 409 `version_conflict`;
    422 `SettingsRefused`; 503 `unavailable`."""
    person = signed_in.person
    try:
        held = await _held(signed_in, connection_id)
        if held is None:
            return _not_found()
        stored = await services.get(SettingsWriter).put(held[1], connection_id, person.household_id, person.id,
                                                        body.revision, _values(body.values))
        if stored is None:
            return _not_found()
        return await _wire(*held, stored)
    except SettingsInvalid as e:
        logs.info(log, "connections.settings.refused", household=person.household_id, person=person.id,
                  connection=connection_id, reason=e.reason)
        return JSONResponse(status_code=422, content=SettingsRefused(
            key=e.key, reason=e.reason, detail="that is not a value this setting takes").model_dump())
    except VersionConflict:
        logs.info(log, "connections.settings.refused", household=person.household_id, person=person.id,
                  connection=connection_id, reason="version_conflict")
        return _error(409, "version_conflict", "the settings changed since you opened them; reload and try again")
    except (ConnectionsUnavailable, PeopleUnavailable):
        return _unavailable()


@router.get("/api/connections/{connection_id}/settings/history", response_model=SettingChanges, responses=_READ)
async def settings_history(signed_in: Person, connection_id: int, limit: Annotated[int, Query(ge=1, le=200)] = 50,
                           before: Annotated[int | None, Query(ge=1)] = None) -> SettingChanges | JSONResponse:
    """200 `SettingChanges`, newest first; 401 `unauthorized`; 404 `not_found`; 503 `unavailable`."""
    household = signed_in.person.household_id
    try:
        if await _held(signed_in, connection_id) is None:
            return _not_found()
        found = await services.get(SettingsReader).history(connection_id, household, limit + 1, before)
        shown = found[:limit]
        return SettingChanges(changes=[SettingChange(id=c.id, key=c.key, edited_by=await _person(household, c.changed_by),
                                                     changed_at=c.changed_at) for c in shown],
                              next_before=shown[-1].id if len(found) > limit else None)
    except (ConnectionsUnavailable, PeopleUnavailable):
        return _unavailable()


def _narrowed(found: Catalogued, domains: list[str]) -> ConnectionCatalogue:
    keep = set(domains)
    return ConnectionCatalogue(
        entities=[CatalogueEntityInfo(entity_id=e.id, name=e.name, domain=e.domain, device_class=e.device_class)
                  for e in found.entities if not keep or e.domain in keep],
        actions=[CatalogueActionInfo(name=a.name, domain=a.domain, looks_up_only=a.looks_up_only) for a in found.actions if not keep or a.domain in keep],
        read_at=datetime.now(UTC))


@router.get("/api/connections/{connection_id}/catalogue", response_model=ConnectionCatalogue, responses=_READ)
async def connection_catalogue(signed_in: Person, connection_id: int,
                               domains: Annotated[list[Domain] | None, Query(max_length=20)] = None) -> ConnectionCatalogue | JSONResponse:
    """200 `ConnectionCatalogue`, read from the service now and narrowed to the `domains` given (all when none); 401
    `unauthorized`; 404 `not_found`; 503 `unavailable`, also when the service did not answer."""
    person = signed_in.person
    try:
        held = await _held(signed_in, connection_id)
        kind = None if held is None else held[1]
        opened = None if kind is None or kind.catalogue is None else await services.get(Connections).opened(
            connection_id, person.household_id, person.id)
        if kind is None or kind.catalogue is None or opened is None:
            return _not_found()
        return _narrowed(await kind.catalogue(opened), domains or [])
    except (ConnectionsUnavailable, CatalogueUnavailable):
        logs.info(log, "connections.catalogue.unavailable", household=person.household_id, connection=connection_id)
        return _unavailable()
