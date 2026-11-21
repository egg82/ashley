"""One service's cameras, behind the Cameras port: the adapter contract. The router (`ashley.cameras.routed`) chooses
which connections are asked."""

from abc import ABC, abstractmethod

from ..connections.model import Opened
from .model import Camera, Still


class CameraSource(ABC):
    @abstractmethod
    async def cameras(self, opened: Opened) -> tuple[Camera, ...]:
        """The cameras the connection reaches that the household lets her look through, and no others. Raises
        CamerasFailed."""

    @abstractmethod
    async def still(self, opened: Opened, camera: Camera) -> Still | None:
        """A picture from `camera` (as `cameras` listed it) now; None when it gives none on demand. Asks once, never
        again. Raises CamerasFailed."""
