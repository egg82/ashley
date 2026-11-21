"""The Cameras service (`ashley.services`): the cameras a household lets her look through and a still from one, as neutral
records (`model`), from every connection that serves the `camera` port and that the household has not switched off,
labelled with its source. It only reads. Callers import this module and `model`; adapters implement
`source.CameraSource`."""

from abc import abstractmethod
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from ..services import Service
from .model import Candidate, LiveConfig, LiveSignal, NotConnected, Roster, Still


class Cameras(Service):
    @classmethod
    def null(cls) -> "Cameras":
        return NullCameras()

    @abstractmethod
    async def connected(self, household_id: int) -> bool:
        """Whether any of the household's connections serves cameras now. Raises CamerasUnavailable."""

    @abstractmethod
    async def roster(self, household_id: int) -> Roster:
        """The cameras of every serving connection that she may look through. A source that fails is named in
        `Roster.unread`, not raised. Raises NotConnected, CamerasUnavailable. Logs `camera.read` with counts and
        duration_ms, never a name."""

    @abstractmethod
    async def look(self, household_id: int, camera_id: str) -> Still:
        """A still from the camera `camera_id`, asked of the connection that holds it. Raises NoSuchCamera, NoStill (it
        gives none on demand), NotConnected, CamerasUnavailable, CamerasFailed. Logs `camera.look` with the source,
        outcome and duration_ms, never a name or a byte."""

    @abstractmethod
    async def live_config(self, household_id: int, camera_id: str) -> LiveConfig:
        """What a browser needs to open a live feed of the camera `camera_id`, which must be one she may look through.
        Raises NoSuchCamera, NoLiveFeed, NotConnected, CamerasUnavailable, CamerasFailed."""

    @abstractmethod
    def live(self, household_id: int, camera_id: str,
             offer: str) -> AbstractAsyncContextManager[AsyncIterator[LiveSignal]]:
        """Pass a browser's `offer` (SDP) to the camera `camera_id` (one she may look through) and yield what the camera's
        service sends back until the feed is closed; the service keeps the feed only while this is open. Raises
        NoSuchCamera, NoLiveFeed, NotConnected, CamerasUnavailable, CamerasFailed on entering. Logs `camera.live` with the
        source, outcome and duration_ms, never a name, an offer or a candidate."""

    @abstractmethod
    async def live_candidate(self, household_id: int, camera_id: str, session_id: str, candidate: Candidate) -> None:
        """Hand a browser's `candidate` for the feed `session_id` of the camera `camera_id` to its service. Raises as
        `live_config`."""


class NullCameras(Cameras):
    """No household has a camera source."""

    async def connected(self, household_id: int) -> bool:
        return False

    async def roster(self, household_id: int) -> Roster:
        raise NotConnected

    async def look(self, household_id: int, camera_id: str) -> Still:
        raise NotConnected

    async def live_config(self, household_id: int, camera_id: str) -> LiveConfig:
        raise NotConnected

    @asynccontextmanager
    async def live(self, household_id: int, camera_id: str, offer: str) -> AsyncGenerator[AsyncIterator[LiveSignal]]:
        raise NotConnected
        yield  # pragma: no cover

    async def live_candidate(self, household_id: int, camera_id: str, session_id: str, candidate: Candidate) -> None:
        raise NotConnected
