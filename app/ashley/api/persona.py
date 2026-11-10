"""The persona page: a signed-in person reads and changes their household's text for her overridable persona sections
(`persona_models` carries the routes' contract). The household is always the session's. Only this route and the wiring
reach `PersonaWriter`, so nothing she does on her own changes how she talks (a boundary test holds that)."""

import logging
from collections.abc import Coroutine, Mapping
from typing import Annotated, Any

from fastapi import APIRouter, Path
from fastapi.responses import JSONResponse

from .. import logs, services
from ..persona import sections
from ..skills import config as skills_config
from ..skills.persona import PersonaOverrides, PersonaUnavailable, PersonaVersion
from ..skills.persona_write import PersonaRefused, PersonaWriter
from .models import ErrorResponse
from .persona_models import (PersonaChange, PersonaDetail, PersonaEditRequest, PersonaRefusalBody, PersonaRevertRequest,
                             PersonaSection)
from .person import Person

router = APIRouter()
log = logging.getLogger("ashley.api")
SectionId = Annotated[str, Path(pattern="^[a-z][a-z0-9-]*$", max_length=40)]
_READ: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "`unauthorized`: no live session"},
    503: {"model": ErrorResponse, "description": "`unavailable`: the database could not be reached"}}
_WRITE: dict[int | str, dict[str, Any]] = {
    **_READ, 403: {"model": ErrorResponse, "description": "`forbidden`: the request came from another site"},
    409: {"model": PersonaRefusalBody, "description": "`refused`, with the reason; nothing changed"},
    422: {"model": ErrorResponse, "description": "a path or body outside its model gets FastAPI's own validation "
          "error, which is not this schema"}}


def _unavailable() -> JSONResponse:
    body = ErrorResponse(code="unavailable", detail="her persona is unavailable right now; try again shortly")
    return JSONResponse(status_code=503, content=body.model_dump())


def _change(v: PersonaVersion) -> PersonaChange:
    return PersonaChange(persona_version=v.version, body=v.body, what=v.what, why=v.why, base_version=v.base_version,
                         restored_from=v.restored_from, person_id=v.person_id, at=v.at)


async def _section(household_id: int, shipped: sections.Section, heads: Mapping[str, PersonaVersion]) -> PersonaSection:
    head = heads.get(shipped.id)
    changelog = await services.get(PersonaOverrides).changelog(household_id, shipped.id) if head else ()
    return PersonaSection(section=shipped.id, label=shipped.label, shipped=shipped.body,
                          override=None if head is None else head.body, persona_version=0 if head is None else head.version,
                          history=[_change(v) for v in changelog])


async def _detail(household_id: int) -> PersonaDetail:
    config, catalogue = skills_config.load(), sections.catalogue()
    heads = await services.get(PersonaOverrides).heads(household_id)
    allowed = {s.id for s in catalogue}
    return PersonaDetail(sections=[await _section(household_id, s, heads) for s in catalogue],
                         orphaned=sorted(i for i, v in heads.items() if i not in allowed and v.body is not None),
                         body_limit=config.max_body_chars, note_limit=config.max_note_chars)


async def _after(person: Person, section: str, change: Coroutine[Any, Any, int]) -> PersonaDetail | JSONResponse:
    """Make `change`, then answer the page as it stands."""
    household, who = person.person.household_id, person.person.id
    try:
        await change
        return await _detail(household)
    except PersonaRefused as e:
        logs.info(log, "persona.refused", household=household, person=who, section=section, reason=e.reason)
        body = PersonaRefusalBody(code="refused", reason=e.reason, detail="that change to her persona was refused")
        return JSONResponse(status_code=409, content=body.model_dump())
    except PersonaUnavailable:
        return _unavailable()


@router.get("/api/persona", response_model=PersonaDetail, responses=_READ)
async def read_persona(signed_in: Person) -> PersonaDetail | JSONResponse:
    """200 `PersonaDetail`; 401 `unauthorized`; 503 `unavailable`."""
    try:
        return await _detail(signed_in.person.household_id)
    except PersonaUnavailable:
        return _unavailable()


@router.put("/api/persona/{section}", response_model=PersonaDetail, responses=_WRITE)
async def edit_persona(signed_in: Person, section: SectionId, body: PersonaEditRequest) -> PersonaDetail | JSONResponse:
    """200 `PersonaDetail` after the change; 401 `unauthorized`; 403 `forbidden`; 409 `PersonaRefusalBody`; 503
    `unavailable`."""
    p = signed_in.person
    change = services.get(PersonaWriter).edit(p.household_id, section, body.body, body.why, body.base_version, p.id)
    return await _after(signed_in, section, change)


@router.post("/api/persona/{section}/revert", response_model=PersonaDetail, responses=_WRITE)
async def revert_persona(signed_in: Person, section: SectionId, body: PersonaRevertRequest) -> PersonaDetail | JSONResponse:
    """200 `PersonaDetail` after the change; 401 `unauthorized`; 403 `forbidden`; 409 `PersonaRefusalBody`; 503
    `unavailable`."""
    p = signed_in.person
    change = services.get(PersonaWriter).revert(p.household_id, section, body.to_version, body.why, body.base_version,
                                                p.id)
    return await _after(signed_in, section, change)

