"""`GET /api/look/{token}`: a bench as its owner sees it, for the browser pod that photographs it
(`ashley.looks.kubernetes`). The token (`ashley.looks.links`) is the only credential, so the pod needs no session; it
names the household, the person, the bench and optionally one piece, is signed under the app's link key and stops
working within minutes. A token naming a piece narrows the answer to that piece. Answered with `no-store`. Logs
`look.page` with the household, bench and piece ids, never the token."""

import logging
import time
from typing import Any, Literal

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from .. import logs, services
from ..connections.deployment_secrets import DeploymentSecrets
from ..files.store import ObjectStore, StoreUnavailable
from ..looks import links
from ..looks.keys import key_of as look_key
from ..runs.runs import RunsUnavailable
from ..workshop.model import Owner
from ..workshop.installs import InstallsUnavailable
from ..workshop.workshop import BenchNotFound, WorkshopUnavailable
from .benches import detail_of, kinds_of
from .look_models import LookPage
from .models import ErrorResponse

router = APIRouter()
log = logging.getLogger("ashley.api.look")
_NOT_STORED = {"Cache-Control": "no-store"}
_TOKEN = {"name": "token", "in": "path", "required": True, "schema": {"type": "string"},
          "description": "The token in a link she was given"}
_ERRORS: dict[int | str, dict[str, Any]] = {404: {"model": ErrorResponse}, 503: {"model": ErrorResponse}}


@router.get("/api/look/{token}", response_model=LookPage, openapi_extra={"parameters": [_TOKEN]}, responses=_ERRORS)
async def read_look(request: Request) -> LookPage | JSONResponse:
    """200 `LookPage`: the bench, or one piece of it, with the kinds; 404 `not_found` for a link that is forged, malformed or
    expired, or a bench or piece that is gone; 503 `unavailable`."""
    key = services.get(DeploymentSecrets).link_key().encode()
    grant = links.check(key, request.path_params["token"], time.time()) if key else None
    if grant is None:
        return _error(404, "not_found", "that link is not valid, or has expired")
    try:
        whole = await detail_of(Owner(grant.household_id, grant.person_id), grant.bench_id, key)
    except BenchNotFound:
        return _error(404, "not_found", "that bench is gone")
    except (WorkshopUnavailable, RunsUnavailable, InstallsUnavailable):
        return _error(503, "unavailable", "the bench cannot be reached right now")
    if grant.piece_id is not None:
        only = [p for p in whole.pieces if p.id == grant.piece_id]
        if not only:
            return _error(404, "not_found", "that piece is gone")
        whole = whole.model_copy(update={"pieces": only, "shelf": [], "recent": []})
    logs.info(log, "look.page", household=grant.household_id, bench=grant.bench_id, piece=grant.piece_id)
    return JSONResponse(LookPage(view=whole, rules=await kinds_of(grant.household_id)).model_dump(mode="json"),
                        headers=_NOT_STORED)


def _error(status: int, code: Literal["not_found", "unavailable"], detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content=ErrorResponse(code=code, detail=detail).model_dump(),
                        headers=_NOT_STORED)


@router.get("/api/looks/{token}", response_class=Response, response_model=None, openapi_extra={"parameters": [_TOKEN]}, responses={
    200: {"content": {"application/octet-stream": {}}, "description": "The picture's bytes"}, **_ERRORS})
async def get_picture(request: Request) -> Response:
    """200 the bytes of a picture she was given, shown in place, for whoever holds a picture link the conversation was
    handed (`ChatLook.url`); 404 `not_found` for a link that is forged, malformed or expired, or whose bytes are gone; 503
    `unavailable` when no store could be asked."""
    key = services.get(DeploymentSecrets).link_key().encode()
    picture = links.check_picture(key, request.path_params["token"], time.time()) if key else None
    if picture is None:
        return _error(404, "not_found", "that link is not valid, or has expired")
    try:
        data = await services.get(ObjectStore).get(look_key(picture.household_id, picture.sha256))
    except StoreUnavailable:
        return _error(503, "unavailable", "the picture cannot be reached right now; try again shortly")
    if data is None:
        return _error(404, "not_found", "that picture is gone")
    left = max(0, picture.expires_at - int(time.time()))
    return Response(data, media_type=picture.media_type, headers={
        "Content-Disposition": "inline", "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "sandbox; default-src 'none'", "Cache-Control": f"private, max-age={left}"})
