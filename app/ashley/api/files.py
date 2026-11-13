"""`GET /api/files/{token}`: the bytes of an image or file piece, for whoever holds a link the bench page was handed
(`bench_file_models.PieceFile.url`). The token is the only credential, so a plain `<img>` or a saved download needs no
session; it names one object, is signed under the app's link key and stops working (`files.json`, `link_ttl_s`). The
bytes are served as the type they were judged to be, with `nosniff` and a sandboxing CSP, shown in place only when the
token says the page may (an image) and as an attachment otherwise, so an uploaded file never runs as a page of this
site. A `Range` header is honoured (206, one range), so a player can seek in a video or audio file. Logs `files.served` with the household, size and duration, never the token or the name."""

import logging
import time
from typing import Literal

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from .. import logs, services
from ..connections.deployment_secrets import DeploymentSecrets
from ..files import links, ranges
from ..files.intake import key_of
from ..files.store import ObjectStore, StoreUnavailable
from .models import ErrorResponse

router = APIRouter()
log = logging.getLogger("ashley.api.files")

_TOKEN = {"name": "token", "in": "path", "required": True, "schema": {"type": "string"},
          "description": "The token in a piece's file link"}


@router.get("/api/files/{token}", response_class=Response, response_model=None, openapi_extra={"parameters": [_TOKEN]},
            responses={200: {"content": {"application/octet-stream": {}}, "description": "The file's bytes"},
                       206: {"content": {"application/octet-stream": {}}, "description": "The range asked"},
                       404: {"model": ErrorResponse}, 416: {"model": ErrorResponse}, 503: {"model": ErrorResponse}})
async def get_file(request: Request) -> Response:
    """200 the bytes, or 206 the one range a `Range` header asked, 416 `refused` when it starts past the end; 404 `not_found` for a link that is forged, malformed, expired or whose bytes no store holds;
    503 `unavailable` when no store could be asked."""
    started = time.monotonic()
    key = services.get(DeploymentSecrets).link_key().encode()
    grant = links.check(key, request.path_params["token"], time.time()) if key else None
    if grant is None:
        return _error(404, "not_found", "that link is not valid, or has expired")
    try:
        data = await services.get(ObjectStore).get(key_of(grant.household_id, grant.sha256))
    except StoreUnavailable:
        return _error(503, "unavailable", "the file cannot be reached right now; try again shortly")
    if data is None:
        return _error(404, "not_found", "that file is gone")
    logs.info(log, "files.served", household=grant.household_id, size=len(data),
              ms=int((time.monotonic() - started) * 1000))
    left = max(0, grant.expires_at - int(time.time()))
    headers = {"Content-Disposition": "inline" if grant.inline else "attachment", "Accept-Ranges": "bytes",
               "X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox; default-src 'none'",
               "Cache-Control": f"private, max-age={left}"}
    asked = ranges.parse(request.headers.get("range"), len(data))
    if asked == "unsatisfiable":
        return JSONResponse(status_code=416, headers={"Content-Range": f"bytes */{len(data)}"}, content=ErrorResponse(
            code="refused", detail="that range is outside the file").model_dump())
    if asked is None:
        return Response(data, media_type=grant.media_type, headers=headers)
    first, last = asked
    return Response(data[first:last + 1], status_code=206, media_type=grant.media_type,
                    headers={**headers, "Content-Range": f"bytes {first}-{last}/{len(data)}"})


def _error(status: int, code: Literal["not_found", "unavailable"], detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content=ErrorResponse(code=code, detail=detail).model_dump())
