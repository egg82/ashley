"""Playing a URL on one of Home Assistant's media players."""

import httpx2

from .. import services
from .client import HomeAssistant
from .homes import Homes, HomesUnavailable

_TIMEOUT_S = 10


async def play_media(home_assistant: HomeAssistant, entity_id: str, url: str) -> bool:
    """Ask Home Assistant to play `url` on `entity_id` (`media_player.kitchen`) through `media_player.play_media`.
    True once Home Assistant accepted the call; False when it could not be reached in time or answered with an error.
    Says nothing about whether playback started on the device."""
    try:
        response = await home_assistant.http.post(
            "/api/services/media_player/play_media",
            json={"entity_id": entity_id, "media_content_id": url, "media_content_type": "music"},
            timeout=_TIMEOUT_S,
        )
    except httpx2.HTTPError:
        return False
    return response.is_success


async def play_for(household_id: int, entity_id: str, url: str) -> bool:
    """`play_media` on the household's own Home Assistant; False when it has none or which one cannot be read now."""
    try:
        home = await services.get(Homes).of(household_id)
    except HomesUnavailable:
        return False
    return False if home is None else await play_media(home.home_assistant, entity_id, url)
