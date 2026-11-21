"""Home Assistant's `camera` entities behind the Cameras port: the household's cameras (`House.states`) that its
`look_cameras` setting names, and a still from the camera proxy (`House.snapshot`), over the one client `Homes` keeps. A
camera the setting does not name is neither listed nor looked through. A camera that gives no still on demand answers
none; nothing here retries. A camera's recordings are the events its own detector captured (`House.events`); a
recording's picture is the middle frame of the event's animated preview, taken with no time stated."""

import asyncio
import io
from datetime import UTC, datetime

from PIL import Image, UnidentifiedImageError

from .. import services
from ..cameras.model import Camera, CamerasFailed, Recording, Still
from ..cameras.source import CameraSource
from ..connections.model import Opened
from . import house_values
from .homes import Homes, HomesUnavailable
from .house import House, HouseUnavailable, Snapshot

NAME = "home_assistant"


async def _house(opened: Opened) -> House | None:
    try:
        home = await services.get(Homes).of(opened.connection.household_id)
    except HomesUnavailable as e:
        raise CamerasFailed("unreachable") from e
    return None if home is None else home.house


class HaCameras(CameraSource):
    async def cameras(self, opened: Opened) -> tuple[Camera, ...]:
        house = await _house(opened)
        if house is None:
            return ()
        try:
            states = await house.states()
        except HouseUnavailable as e:
            raise CamerasFailed("unreachable") from e
        allowed = (await house_values.read(opened.connection.household_id)).look_cameras
        return tuple(Camera(s.id, s.name, NAME, opened.connection.id) for s in states
                     if s.domain == "camera" and s.id in allowed)

    async def still(self, opened: Opened, camera: Camera) -> Still | None:
        house = await _house(opened)
        if house is None:
            raise CamerasFailed("unreachable")
        try:
            got = await house.snapshot(camera.id)
        except HouseUnavailable as e:
            raise CamerasFailed("unreachable") from e
        return None if got is None else Still(got.data, got.media_type, datetime.now(UTC))

    async def recordings(self, opened: Opened, camera: Camera) -> tuple[Recording, ...]:
        house = await _house(opened)
        if house is None:
            return ()
        try:
            return tuple(Recording(e.id, camera.id, e.title) for e in await house.events(camera.id))
        except HouseUnavailable as e:
            raise CamerasFailed("unreachable") from e

    async def recording_still(self, opened: Opened, camera: Camera, recording_id: str) -> Still | None:
        house = await _house(opened)
        if house is None:
            raise CamerasFailed("unreachable")
        try:
            got = await house.event_picture(camera.id, recording_id)
        except HouseUnavailable as e:
            raise CamerasFailed("unreachable") from e
        if got is None:
            return None
        data, media_type = await asyncio.to_thread(_middle_frame, got.picture)
        return Still(data, media_type, None, got.title)


def _middle_frame(preview: Snapshot) -> tuple[bytes, str]:
    """The middle frame of a preview (a single picture is its own middle) as a PNG. Raises CamerasFailed."""
    try:
        with Image.open(io.BytesIO(preview.data)) as animated:
            animated.seek(getattr(animated, "n_frames", 1) // 2)
            out = io.BytesIO()
            animated.convert("RGB").save(out, "PNG")
    except (UnidentifiedImageError, OSError, EOFError, Image.DecompressionBombError) as e:
        raise CamerasFailed("unrecognised") from e
    return out.getvalue(), "image/png"
