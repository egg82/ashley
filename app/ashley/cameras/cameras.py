"""The Cameras service (`ashley.services`): the cameras a household lets her look through and a still from one, as neutral
records (`model`), from every connection that serves the `camera` port and that the household has not switched off,
labelled with its source. It only reads. Callers import this module and `model`; adapters implement
`source.CameraSource`."""

from abc import abstractmethod

from ..services import Service
from .model import NotConnected, Recording, Roster, Still


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
    async def recordings(self, household_id: int, camera_id: str) -> tuple[Recording, ...]:
        """What the camera `camera_id` (one she may look through) has captured, newest first, at most
        the count the router was given. Raises NoSuchCamera, NotConnected, CamerasUnavailable, CamerasFailed. Logs
        `camera.recordings` with the source, outcome, count and duration_ms, never a title or a name."""

    @abstractmethod
    async def look_recording(self, household_id: int, camera_id: str, recording_id: str) -> Still:
        """One picture of a recording of the camera `camera_id`; its `taken` is None unless the source states a time.
        Raises NoSuchCamera, NoSuchRecording, NotConnected, CamerasUnavailable, CamerasFailed. Logs `camera.look` with
        the source, outcome and duration_ms, never a title, a name or a byte."""


class NullCameras(Cameras):
    """No household has a camera source."""

    async def connected(self, household_id: int) -> bool:
        return False

    async def roster(self, household_id: int) -> Roster:
        raise NotConnected

    async def look(self, household_id: int, camera_id: str) -> Still:
        raise NotConnected

    async def recordings(self, household_id: int, camera_id: str) -> tuple[Recording, ...]:
        raise NotConnected

    async def look_recording(self, household_id: int, camera_id: str, recording_id: str) -> Still:
        raise NotConnected
