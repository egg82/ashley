"""A bench's kind of work, and the household's skills (`ashley.skills.skills.Skills`) a person reads and steers: set
a bench's kind of work, read a kind's skill with its changelog, pin it so her edits wait for approval, approve or decline
one that waits, and roll it back. Her own edits are made by her tools, not here. A skill is the household's, so any
person of it reads and changes it; a bench is only its owner's."""

from collections.abc import Coroutine
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from .. import services
from ..skills.skills import Edited, SkillRefused, Skills, SkillsUnavailable
from ..workshop.workshop import BenchNotFound, Workshop, WorkshopUnavailable
from .benches import BENCH_ERRORS, WRITE_ERRORS, not_found, owner_of, summary, unavailable
from .models import ErrorResponse
from .person import Person
from .skill_models import PinRequest, RollbackRequest, SkillDetail, SkillRefusal, WorkRequest, detail_of
from .workshop_models import BenchSummary

router = APIRouter()
_REFUSED: dict[int | str, dict[str, Any]] = {
    **WRITE_ERRORS, 422: BENCH_ERRORS[422], 404: {"model": ErrorResponse, "description": "`not_found`: no such skill"},
    409: {"model": SkillRefusal, "description": "`refused`, with the reason; nothing changed"}}


def _refused(e: SkillRefused) -> JSONResponse:
    body = SkillRefusal(code="refused", reason=e.reason, detail="that change to the skill was refused")
    return JSONResponse(status_code=409, content=body.model_dump())


async def _label(household_id: int, kind: str) -> str:
    return next((k.label for k in await services.get(Skills).kinds(household_id) if k.kind == kind), kind)


def _missing() -> JSONResponse:
    return JSONResponse(status_code=404, content=ErrorResponse(code="not_found", detail="no such skill").model_dump())


async def _after(household_id: int, kind: str, change: Coroutine[Any, Any, Edited | None] | None) -> SkillDetail | JSONResponse:
    """Make `change`, if any, then answer with the kind's skill as it loads now."""
    try:
        if change is not None:
            await change
        skills = services.get(Skills)
        skill = await skills.current(household_id, kind)
        if skill is None:
            return _missing()
        return detail_of(skill, await _label(household_id, kind), await skills.changelog(household_id, kind))
    except SkillRefused as e:
        return _missing() if e.reason == "unknown_kind" else _refused(e)
    except SkillsUnavailable:
        return unavailable()


@router.put("/api/benches/{bench_id}/work", response_model=BenchSummary, responses={
    **WRITE_ERRORS, **BENCH_ERRORS})
async def set_work(signed_in: Person, bench_id: int, body: WorkRequest) -> BenchSummary | JSONResponse:
    """200 `BenchSummary` with its kind of work set (null clears it); 401 `unauthorized`; 403 `forbidden`; 404
    `not_found`; 422 for a slug that is not of the shape, or a new kind with no label; 503 `unavailable`. A slug the
    household has no kind for starts one, named by `label`."""
    owner = owner_of(signed_in)
    try:
        if body.work is not None:
            await _start(owner.household_id, body.work, body.label)
    except SkillRefused:
        return JSONResponse(status_code=422, content=ErrorResponse(code="refused", detail="not a kind of work").model_dump())
    except SkillsUnavailable:
        return unavailable()
    try:
        bench = await services.get(Workshop).set_work(owner, bench_id, body.work)
    except BenchNotFound:
        return not_found()
    except WorkshopUnavailable:
        return unavailable()
    return summary(bench)


@router.get("/api/skills/{kind}", response_model=SkillDetail, responses={
    401: WRITE_ERRORS[401], 404: _REFUSED[404], 422: BENCH_ERRORS[422], 503: WRITE_ERRORS[503]})
async def read_skill(signed_in: Person, kind: str) -> SkillDetail | JSONResponse:
    """200 `SkillDetail`; 401 `unauthorized`; 404 `not_found` for an unknown kind or one with no skill yet; 503
    `unavailable`."""
    return await _after(signed_in.person.household_id, kind, None)


@router.put("/api/skills/{kind}/pin", response_model=SkillDetail, responses=_REFUSED)
async def pin_skill(signed_in: Person, kind: str, body: PinRequest) -> SkillDetail | JSONResponse:
    """200 `SkillDetail`, pinned or not (her edits of a pinned skill wait for approval); 401; 403; 404 `not_found`
    when the kind has no skill to show; 503."""
    household = signed_in.person.household_id
    return await _after(household, kind, _pinned(household, kind, body.pinned))


@router.post("/api/skills/{kind}/rollback", response_model=SkillDetail, responses=_REFUSED)
async def rollback_skill(signed_in: Person, kind: str, body: RollbackRequest) -> SkillDetail | JSONResponse:
    """200 `SkillDetail` with the earlier text back as a new version; 401; 403; 404; 409 `SkillRefusal`
    (`no_such_version`, `unchanged`); 503."""
    household = signed_in.person.household_id
    return await _after(household, kind, services.get(Skills).rollback(
        household, kind, body.to_version, "Rolled back by a person", None, signed_in.person.id))


@router.post("/api/skills/{kind}/proposals/{version}/approve", response_model=SkillDetail, responses=_REFUSED)
async def approve_proposal(signed_in: Person, kind: str, version: int) -> SkillDetail | JSONResponse:
    """200 `SkillDetail` with her waiting edit live; 401; 403; 404; 409 `SkillRefusal` (`not_proposed`, or `stale`
    when the skill moved on since she proposed it); 503."""
    household = signed_in.person.household_id
    return await _after(household, kind, services.get(Skills).decide(household, kind, version, True))


@router.post("/api/skills/{kind}/proposals/{version}/decline", response_model=SkillDetail, responses=_REFUSED)
async def decline_proposal(signed_in: Person, kind: str, version: int) -> SkillDetail | JSONResponse:
    """200 `SkillDetail` with her waiting edit declined; 401; 403; 404; 409 `SkillRefusal` (`not_proposed`); 503."""
    household = signed_in.person.household_id
    return await _after(household, kind, services.get(Skills).decide(household, kind, version, False))


async def _start(household_id: int, kind: str, label: str | None) -> None:
    """Makes `kind` the household's when it is not; raises SkillRefused (`unknown_kind`) for a new one with no label."""
    skills = services.get(Skills)
    if kind in {k.kind for k in await skills.kinds(household_id)}:
        return
    if label is None:
        raise SkillRefused("unknown_kind")
    await skills.add_kind(household_id, kind, label)


async def _pinned(household_id: int, kind: str, pinned: bool) -> None:
    await services.get(Skills).pin(household_id, kind, pinned)
