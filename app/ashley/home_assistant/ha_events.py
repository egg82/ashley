"""What a camera's own detector captured, from Home Assistant's `nest` media source: the camera entity's device
(`config/entity_registry/list`), the device's events (WebSocket `media_source/browse_media`), and an event's preview
picture (REST GET of the thumbnail path the browse gives). A camera of another platform, or a device the source does not
know, has no events."""

from .ha_json import JsonObject, obj, rows, text
from .ha_registry import Registries
from .ha_rest import Rest
from .ha_socket import Commands
from .house import Event, HouseRejected, Preview, Snapshot

PLATFORM = "nest"
ROOT = "media-source://nest/"
STEP = "event_thumbnail"


class Events:
    def __init__(self, rest: Rest, commands: Commands, registries: Registries) -> None:
        self._rest = rest
        self._commands = commands
        self._registries = registries

    async def of(self, camera: str) -> tuple[Event, ...]:
        return tuple(Event(text(c.get("media_content_id")), text(c.get("title"))) for c in await self._children(camera)
                     if text(c.get("media_content_id")))

    async def picture(self, camera: str, event_id: str) -> Preview | None:
        for child in await self._children(camera):
            if text(child.get("media_content_id")) != event_id:
                continue
            path = text(child.get("thumbnail"))
            got = await self._rest.image(path, STEP, (404,)) if path.startswith("/") else None
            return None if got is None else Preview(text(child.get("title")), Snapshot(*got))
        return None

    async def _children(self, camera: str) -> list[JsonObject]:
        device = await self._device(camera)
        if device is None:
            return []
        try:
            browsed = await self._commands.run({"type": "media_source/browse_media", "media_content_id": ROOT + device})
        except HouseRejected:
            return []
        return rows(obj(browsed).get("children"))

    async def _device(self, camera: str) -> str | None:
        entry = next((e for e in await self._registries.rows("entity") if text(e.get("entity_id")) == camera), None)
        if entry is None or text(entry.get("platform")) != PLATFORM:
            return None
        return text(entry.get("device_id")) or None

