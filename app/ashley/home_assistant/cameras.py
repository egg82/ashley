"""Home Assistant's `camera` entities behind the Cameras port: the household's cameras (`House.states`) that its
`look_cameras` setting names, and a still from the camera proxy (`House.snapshot`), over the one client `Homes` keeps. A
camera the setting does not name is neither listed nor looked through. A camera that gives no still on demand answers
none; nothing here retries."""

from datetime import UTC, datetime

from .. import services
from ..cameras.model import Camera, CamerasFailed, Still
from ..cameras.source import CameraSource
from ..connections.model import Opened
from . import house_values
from .homes import Homes, HomesUnavailable
from .house import House, HouseUnavailable

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
