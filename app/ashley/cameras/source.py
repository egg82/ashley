"""One service's cameras, behind the Cameras port: the adapter contract. The router (`ashley.cameras.routed`) chooses
which connections are asked."""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager

from ..connections.model import Opened
from .model import Camera, Candidate, LiveConfig, LiveSignal, Still


class CameraSource(ABC):
    @abstractmethod
    async def cameras(self, opened: Opened) -> tuple[Camera, ...]:
        """The cameras the connection reaches that the household lets her look through, and no others. Raises
        CamerasFailed."""

    @abstractmethod
    async def still(self, opened: Opened, camera: Camera) -> Still | None:
        """A picture from `camera` (as `cameras` listed it) now; None when it gives none on demand. Asks once, never
        again. Raises CamerasFailed."""

    @abstractmethod
    async def live_config(self, opened: Opened, camera: Camera) -> LiveConfig:
        """What a browser needs to open a live feed of `camera`. Raises CamerasFailed, NoLiveFeed."""

    @abstractmethod
    def live(self, opened: Opened, camera: Camera, offer: str) -> AbstractAsyncContextManager[AsyncIterator[LiveSignal]]:
        """Pass the browser's `offer` (SDP) to `camera` and yield what the service sends back until the feed is closed.
        The service keeps the feed only while this is open. Raises CamerasFailed, NoLiveFeed on entering."""

    @abstractmethod
    async def live_candidate(self, opened: Opened, camera: Camera, session_id: str, candidate: Candidate) -> None:
        """Hand the browser's `candidate` for the feed `session_id` to the service. Raises CamerasFailed, NoLiveFeed."""
