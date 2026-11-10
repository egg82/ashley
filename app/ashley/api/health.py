"""Liveness: the process is up."""

from fastapi import APIRouter, Request

from ..settings import Settings
from .models import HealthResponse

router = APIRouter()


@router.get("/api/health")
async def get_health(request: Request) -> HealthResponse:
    """Liveness. Never touches the database, so a database outage does not restart the pods."""
    settings: Settings = request.app.state.settings
    return HealthResponse(status="ok", version=settings.build_version)
