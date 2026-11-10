"""Where the house is: Home Assistant's `zone.home`, whose attributes carry its latitude and longitude. The
coordinates are people's data and are never logged."""

import math
from dataclasses import dataclass

import httpx2
from pydantic import BaseModel, ValidationError

from .client import HomeAssistant

_TIMEOUT_S = 5


@dataclass(frozen=True)
class Coordinates:
    latitude: float
    longitude: float


class HomeUnknown(Exception):
    """The house's location could not be read: HA unreachable, an error status, or no usable coordinates. `reason` is
    a code, never a body or a coordinate."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class _Zone(BaseModel):
    attributes: dict[str, object]


async def home(home_assistant: HomeAssistant) -> Coordinates:
    """The house's coordinates from `/api/states/zone.home`. Raises HomeUnknown."""
    try:
        response = await home_assistant.http.get("/api/states/zone.home", timeout=_TIMEOUT_S)
    except httpx2.HTTPError as e:
        raise HomeUnknown("unreachable") from e
    if not response.is_success:
        raise HomeUnknown(f"http_{response.status_code}")
    try:
        attributes = _Zone.model_validate_json(response.content).attributes
    except ValidationError as e:
        raise HomeUnknown("malformed") from e
    return Coordinates(_degrees(attributes.get("latitude")), _degrees(attributes.get("longitude")))


def _degrees(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise HomeUnknown("no_coordinates")
    return float(value)
