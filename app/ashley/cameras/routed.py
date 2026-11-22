"""The Cameras port wired: every connection serving `camera`, the household's and each person's
(`ashley.connections.ports.opened_all`, which honours the household's switches), is read by the adapter of its kind, and
what they hold is combined, each camera labelled with its source. A connection of a kind with no adapter is skipped; a source that fails is `unread`, so one service being down never
hides the others, nor reads as having no camera."""

import logging
import time
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable, Mapping
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from .. import logs, services
from ..connections import ports
from ..connections.connections import Connections, ConnectionsUnavailable
from ..connections.model import Opened
from .cameras import Cameras
from .model import (Camera, CamerasFailed, CamerasUnavailable, Candidate, DetectionRecorder, LiveConfig, LiveSignal, NoLiveFeed, NoStill,
                    NoSuchCamera, NoSuchRecording, NotConnected, Recording, Roster, Still)
from .source import CameraSource

log = logging.getLogger("ashley.cameras")


class RoutedCameras(Cameras):
    def __init__(self, adapters: Mapping[str, CameraSource], max_recordings: int) -> None:
        self._adapters = dict(adapters)
        self._max_recordings = max_recordings

    async def _serving(self, household_id: int) -> list[Opened]:
        try:
            found = await ports.opened_all(services.get(Connections), "camera", household_id, everyone=True)
        except ConnectionsUnavailable as e:
            raise CamerasUnavailable from e
        return [o for o in found if o.connection.kind in self._adapters]

    async def connected(self, household_id: int) -> bool:
        return bool(await self._serving(household_id))

    async def roster(self, household_id: int) -> Roster:
        began = time.monotonic()
        serving = await self._serving(household_id)
        if not serving:
            raise NotConnected
        cameras: list[Camera] = []
        unread: list[str] = []
        for opened in serving:
            kind = opened.connection.kind
            try:
                cameras.extend(await self._adapters[kind].cameras(opened))
            except CamerasFailed as e:
                logs.warning(log, "camera.unread", source=kind, connection=opened.connection.id, reason=e.reason)
                unread.append(kind)
        logs.info(log, "camera.read", sources=len(serving), cameras=len(cameras), unread=len(unread),
                  duration_ms=int((time.monotonic() - began) * 1000))
        return Roster(tuple(cameras), tuple(unread))

    async def _through[T](self, household_id: int, camera_id: str, event: str,
                          ask: Callable[[CameraSource, Opened, Camera], Awaitable[T]]) -> tuple[str, T]:
        """What `ask` gives of the first serving connection that lists `camera_id`, with its kind. Raises NotConnected,
        NoSuchCamera, or the last CamerasFailed when every holder failed."""
        serving = await self._serving(household_id)
        if not serving:
            raise NotConnected
        failed: CamerasFailed | None = None
        for opened in serving:
            kind = opened.connection.kind
            try:
                held = next((c for c in await self._adapters[kind].cameras(opened) if c.id == camera_id), None)
                if held is None:
                    continue
                return kind, await ask(self._adapters[kind], opened, held)
            except CamerasFailed as e:
                logs.warning(log, f"camera.{event}_failed", source=kind, connection=opened.connection.id, reason=e.reason)
                failed = e
        if failed is not None:
            raise failed
        raise NoSuchCamera

    async def look(self, household_id: int, camera_id: str) -> Still:
        began = time.monotonic()
        kind, got = await self._through(household_id, camera_id, "look", lambda a, o, c: a.still(o, c))
        _looked(kind, got, began)
        if got is None:
            raise NoStill
        return got

    async def recordings(self, household_id: int, camera_id: str) -> tuple[Recording, ...]:
        began = time.monotonic()
        kind, got = await self._through(household_id, camera_id, "recordings", lambda a, o, c: a.recordings(o, c))
        kept = got[:self._max_recordings]
        logs.info(log, "camera.recordings", source=kind, outcome="ok" if kept else "none", count=len(kept),
                  duration_ms=_ms(began))
        return kept

    async def look_recording(self, household_id: int, camera_id: str, recording_id: str) -> Still:
        began = time.monotonic()
        kind, got = await self._through(household_id, camera_id, "look",
                                        lambda a, o, c: a.recording_still(o, c, recording_id))
        _looked(kind, got, began)
        if got is None:
            raise NoSuchRecording
        return got


    async def follow(self, household_id: int, record: DetectionRecorder) -> int:
        serving = await self._serving(household_id)
        kinds = {o.connection.kind for o in serving}
        followed, failed = 0, None
        for kind, adapter in self._adapters.items():
            if kind not in kinds:
                await self._quietly(household_id, kind, adapter.stop(household_id))
        for opened in serving:
            try:
                followed += await self._adapters[opened.connection.kind].follow(opened, record)
            except CamerasFailed as e:
                logs.warning(log, "camera.follow_failed", source=opened.connection.kind, connection=opened.connection.id,
                             reason=e.reason)
                failed = e
        if failed is not None and serving and followed == 0:
            raise failed
        return followed

    async def _quietly(self, household_id: int, kind: str, stopping: Awaitable[None]) -> None:
        try:
            await stopping
        except CamerasFailed as e:
            logs.warning(log, "camera.follow_failed", source=kind, household=household_id, reason=e.reason)

    async def live_config(self, household_id: int, camera_id: str) -> LiveConfig:
        _, got = await self._through(household_id, camera_id, "live", lambda a, o, c: a.live_config(o, c))
        return got

    @asynccontextmanager
    async def live(self, household_id: int, camera_id: str, offer: str) -> AsyncGenerator[AsyncIterator[LiveSignal]]:
        began = time.monotonic()

        async def start(adapter: CameraSource, opened: Opened, camera: Camera) -> AbstractAsyncContextManager[
                AsyncIterator[LiveSignal]]:
            return adapter.live(opened, camera, offer)

        kind, feed = await self._through(household_id, camera_id, "live", start)
        outcome = "ok"
        try:
            async with feed as signals:
                yield signals
        except (CamerasFailed, NoLiveFeed) as e:
            outcome = e.reason if isinstance(e, CamerasFailed) else "no_live_feed"
            raise
        finally:
            logs.info(log, "camera.live", source=kind, outcome=outcome, duration_ms=_ms(began))

    async def live_candidate(self, household_id: int, camera_id: str, session_id: str, candidate: Candidate) -> None:
        await self._through(household_id, camera_id, "live",
                            lambda a, o, c: a.live_candidate(o, c, session_id, candidate))


def _ms(began: float) -> int:
    return int((time.monotonic() - began) * 1000)


def _looked(kind: str, got: Still | None, began: float) -> None:
    logs.info(log, "camera.look", source=kind, outcome="none" if got is None else "ok",
              bytes=0 if got is None else len(got.data), duration_ms=_ms(began))
