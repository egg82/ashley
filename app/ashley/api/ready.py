"""Readiness: this pod can serve requests that need the database."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from .. import services
from ..db.database import Database
from .models import ErrorResponse, ReadyResponse

router = APIRouter()


@router.get("/api/ready", response_model=ReadyResponse, responses={503: {"model": ErrorResponse}})
async def get_ready() -> ReadyResponse | JSONResponse:
    """Readiness. 200 when a connection opens, reporting whether it reached a writable primary; 503
    `database_unavailable` when none does."""
    found = await services.get(Database).probe()
    if not found.reachable:
        error = ErrorResponse(code="database_unavailable", detail="no database connection could be opened")
        return JSONResponse(status_code=503, content=error.model_dump())
    return ReadyResponse(ready=True, writable=found.writable)
