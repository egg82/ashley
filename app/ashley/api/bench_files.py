"""A person's upload to a bench (`POST /api/benches/{id}/files`): the file's bytes as the request body, kept in the
object store and added as an `image` or `file` piece through the ordinary Add (`ashley.workshop.bench_file`), so it
is shown live, logged and undone like any piece. The type the page says it is (`X-File-Type`) is only checked against
what the bytes are; the name arrives percent-encoded in `X-File-Name`, never in the URL or the logs."""

from typing import Literal

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse

from ..files.intake import Reason, Refused
from ..files.store import StoreUnavailable
from ..workshop import bench_file
from ..workshop.model import By
from ..workshop.workshop import BenchClosed, BenchNotFound, WorkshopUnavailable
from .benches import BENCH_ERRORS, RULES, WRITE_ERRORS, not_found, owner_of, unavailable
from .models import ErrorResponse
from .person import Uploading
from .workshop_models import CommandApplied, CommandRefused

router = APIRouter()
CODES: dict[Reason, tuple[int, Literal["too_large", "unsupported", "refused"], str]] = {
    "empty": (422, "refused", "the file is empty"),
    "too_large": (413, "too_large", "that file is larger than a bench takes"),
    "type_not_allowed": (415, "unsupported", "that kind of file is not taken"),
    "type_mismatch": (415, "unsupported", "the file is not the type it says it is")}


def _error(status: int, code: Literal["closed", "too_large", "unsupported", "refused"], detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content=ErrorResponse(code=code, detail=detail).model_dump())


async def read_body(request: Request, limit: int) -> bytes | None:
    """The request's body, None when it is longer than `limit`."""
    length = request.headers.get("content-length")
    if length is not None and length.isdigit() and int(length) > limit:
        return None
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > limit:
            return None
    return bytes(body)


@router.post("/api/benches/{bench_id}/files", response_model=CommandApplied, openapi_extra={"requestBody": {
    "required": True, "content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}}}},
             responses={**WRITE_ERRORS, **BENCH_ERRORS,
                        409: {"model": CommandRefused, "description": "`refused`, with the reason (`full`); logged "
                              "as the bench's next seq. The bytes stay stored."},
                        410: {"model": ErrorResponse, "description": "`closed`: the bench is closed"},
                        413: {"model": ErrorResponse, "description": "`too_large`: over `files.json`'s `max_bytes`"},
                        415: {"model": ErrorResponse, "description": "`unsupported`: the bytes are no type a bench "
                              "takes, or not the type `X-File-Type` says"}})
async def upload_file(signed_in: Uploading, bench_id: int, request: Request,
                      x_file_name: str = Header(default="file"), x_file_type: str = Header(default="")
                      ) -> CommandApplied | JSONResponse:
    """200 `CommandApplied`, the new piece's id; 401 `unauthorized`; 403 `forbidden`; 404 `not_found`; 409
    `CommandRefused`; 410 `closed`; 413 `too_large`; 415 `unsupported`; 422 `refused` for an empty file; 503
    `unavailable` (the workshop or the store could not be reached; nothing was added)."""
    owner = owner_of(signed_in)
    data = await read_body(request, bench_file.CONFIG.max_bytes)
    if data is None:
        return _error(*CODES["too_large"])
    try:
        _, applied = await bench_file.add_file(owner, bench_id, By(owner.person_id), data, x_file_name, x_file_type,
                                               RULES)
    except Refused as e:
        return _error(*CODES[e.reason])
    except BenchNotFound:
        return not_found()
    except BenchClosed:
        return _error(410, "closed", "the bench is closed")
    except (WorkshopUnavailable, StoreUnavailable):
        return unavailable()
    if applied.outcome != "accepted":
        refused = CommandRefused(code="refused", reason=applied.outcome, seq=applied.seq,
                                 detail="the bench refused that file")
        return JSONResponse(status_code=409, content=refused.model_dump())
    return CommandApplied(seq=applied.seq, piece_id=applied.piece_id)
