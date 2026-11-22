"""One service's cameras, behind the Cameras port: the adapter contract. The router (`ashley.cameras.routed`) chooses
which connections are asked."""

from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from ..connections.model import Opened
from .model import Camera, Candidate, DetectionRecorder, LiveConfig, LiveSignal, NoLiveFeed, Recording, Still


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

    async def follow(self, opened: Opened, record: DetectionRecorder) -> int:
        """Follow the detectors of the cameras `cameras` lists, each detection handed to `record` as it happens, in
        place of whatever was followed before; how many detectors are followed. A source with no detector events
        follows none. A detection while the source was unreachable is not told. Raises CamerasFailed."""
        return 0

    async def stop(self, household_id: int) -> None:
        """Stop following the household's detectors. Raises CamerasFailed."""
        return None

    async def live_config(self, opened: Opened, camera: Camera) -> LiveConfig:
        """What a browser needs to open a live feed of `camera`. A source with no feed raises NoLiveFeed, as this does.
        Raises CamerasFailed, NoLiveFeed."""
        raise NoLiveFeed

    def live(self, opened: Opened, camera: Camera, offer: str) -> AbstractAsyncContextManager[AsyncIterator[LiveSignal]]:
        """Pass the browser's `offer` (SDP) to `camera` and yield what the service sends back until the feed is closed.
        The service keeps the feed only while this is open. Raises CamerasFailed, NoLiveFeed on entering (here, always)."""
        return _no_feed()

    async def live_candidate(self, opened: Opened, camera: Camera, session_id: str, candidate: Candidate) -> None:
        """Hand the browser's `candidate` for the feed `session_id` to the service. Raises CamerasFailed, NoLiveFeed."""
        raise NoLiveFeed


@asynccontextmanager
async def _no_feed() -> AsyncGenerator[AsyncIterator[LiveSignal]]:
    raise NoLiveFeed
    yield _empty()


async def _empty() -> AsyncIterator[LiveSignal]:
    return
    yield
