"""Home Assistant's `camera` entities behind the Cameras port: the household's cameras (`House.states`) that its
`look_cameras` setting names, and a still from the camera proxy (`House.snapshot`), over the one client `Homes` keeps. A
camera the setting does not name is neither listed nor looked through. A camera that gives no still on demand answers
none; nothing here retries."""

from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, datetime

from .. import services
from ..cameras.model import Camera, CamerasFailed, Candidate, LiveConfig, LiveSignal, NoLiveFeed, Still
from ..cameras.source import CameraSource
from ..connections.model import Opened
from . import house_values
from .homes import Homes, HomesUnavailable
from .house import House, HouseRejected, HouseUnavailable

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

    async def live_config(self, opened: Opened, camera: Camera) -> LiveConfig:
        house = await _live_house(opened)
        try:
            return await house.live_config(camera.id)
        except HouseRejected as e:
            raise NoLiveFeed from e
        except HouseUnavailable as e:
            raise CamerasFailed("unreachable") from e

    def live(self, opened: Opened, camera: Camera, offer: str) -> AbstractAsyncContextManager[AsyncIterator[LiveSignal]]:
        return self._live(opened, camera, offer)

    @asynccontextmanager
    async def _live(self, opened: Opened, camera: Camera, offer: str) -> AsyncGenerator[AsyncIterator[LiveSignal]]:
        house = await _live_house(opened)
        try:
            async with house.live_feed(camera.id, offer) as signals:
                yield signals
        except HouseRejected as e:
            raise NoLiveFeed from e
        except HouseUnavailable as e:
            raise CamerasFailed("unreachable") from e

    async def live_candidate(self, opened: Opened, camera: Camera, session_id: str, candidate: Candidate) -> None:
        house = await _live_house(opened)
        try:
            await house.live_candidate(camera.id, session_id, candidate)
        except HouseRejected as e:
            raise NoLiveFeed from e
        except HouseUnavailable as e:
            raise CamerasFailed("unreachable") from e


async def _live_house(opened: Opened) -> House:
    house = await _house(opened)
    if house is None:
        raise CamerasFailed("unreachable")
    return house
