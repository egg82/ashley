"""One service's cameras, behind the Cameras port: the adapter contract. The router (`ashley.cameras.routed`) chooses
which connections are asked."""

from abc import ABC, abstractmethod

from ..connections.model import Opened
from .model import Camera, Recording, Still


class CameraSource(ABC):
    @abstractmethod
    async def cameras(self, opened: Opened) -> tuple[Camera, ...]:
        """The cameras the connection reaches that the household lets her look through, and no others. Raises
        CamerasFailed."""

    @abstractmethod
    async def still(self, opened: Opened, camera: Camera) -> Still | None:
        """A picture from `camera` (as `cameras` listed it) now; None when it gives none on demand. Asks once, never
        again. Raises CamerasFailed."""

    async def recordings(self, opened: Opened, camera: Camera) -> tuple[Recording, ...]:
        """What `camera`'s own detector captured, newest first; empty when the source keeps none for it. Raises
        CamerasFailed."""
        return ()

    async def recording_still(self, opened: Opened, camera: Camera, recording_id: str) -> Still | None:
        """One picture of the recording `recording_id` (as `recordings` listed it); None when the source has no such
        recording for `camera`. Asks once. Raises CamerasFailed."""
        return None
