"""The Cameras port wired: every connection serving `camera` (`ashley.connections.ports.opened_all`, which honours the
household's switches) is read by the adapter of its kind, and what they hold is combined, each camera labelled with its
source. A connection of a kind with no adapter is skipped; a source that fails is `unread`, so one service being down never
hides the others, nor reads as having no camera."""

import logging
import time
from collections.abc import AsyncGenerator, AsyncIterator, Mapping
from contextlib import asynccontextmanager

from .. import logs, services
from ..connections import ports
from ..connections.connections import Connections, ConnectionsUnavailable
from ..connections.model import Opened
from .cameras import Cameras
from .model import (Camera, CamerasFailed, CamerasUnavailable, Candidate, LiveConfig, LiveSignal, NoLiveFeed, NoStill,
                    NoSuchCamera, NotConnected, Roster, Still)
from .source import CameraSource

log = logging.getLogger("ashley.cameras")


class RoutedCameras(Cameras):
    def __init__(self, adapters: Mapping[str, CameraSource]) -> None:
        self._adapters = dict(adapters)

    async def _serving(self, household_id: int) -> list[Opened]:
        try:
            found = await ports.opened_all(services.get(Connections), "camera", household_id)
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

    async def look(self, household_id: int, camera_id: str) -> Still:
        began = time.monotonic()
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
                got = await self._adapters[kind].still(opened, held)
            except CamerasFailed as e:
                logs.warning(log, "camera.look_failed", source=kind, connection=opened.connection.id, reason=e.reason)
                failed = e
                continue
            outcome = "none" if got is None else "ok"
            logs.info(log, "camera.look", source=kind, outcome=outcome, bytes=0 if got is None else len(got.data),
                      duration_ms=int((time.monotonic() - began) * 1000))
            if got is None:
                raise NoStill
            return got
        if failed is not None:
            raise failed
        raise NoSuchCamera

    async def _held(self, household_id: int, camera_id: str) -> tuple[Opened, Camera]:
        """The serving connection that holds the camera, and the camera as it lists it. Raises NoSuchCamera, NotConnected,
        CamerasUnavailable, CamerasFailed (when no connection held it and one failed)."""
        serving = await self._serving(household_id)
        if not serving:
            raise NotConnected
        failed: CamerasFailed | None = None
        for opened in serving:
            try:
                held = next((c for c in await self._adapters[opened.connection.kind].cameras(opened) if c.id == camera_id),
                            None)
            except CamerasFailed as e:
                failed = e
                continue
            if held is not None:
                return opened, held
        if failed is not None:
            raise failed
        raise NoSuchCamera

    async def live_config(self, household_id: int, camera_id: str) -> LiveConfig:
        opened, camera = await self._held(household_id, camera_id)
        return await self._adapters[opened.connection.kind].live_config(opened, camera)

    @asynccontextmanager
    async def live(self, household_id: int, camera_id: str, offer: str) -> AsyncGenerator[AsyncIterator[LiveSignal]]:
        began = time.monotonic()
        opened, camera = await self._held(household_id, camera_id)
        kind = opened.connection.kind
        outcome = "ok"
        try:
            async with self._adapters[kind].live(opened, camera, offer) as signals:
                yield signals
        except (CamerasFailed, NoLiveFeed) as e:
            outcome = e.reason if isinstance(e, CamerasFailed) else "no_live_feed"
            raise
        finally:
            logs.info(log, "camera.live", source=kind, outcome=outcome, duration_ms=int((time.monotonic() - began) * 1000))

    async def live_candidate(self, household_id: int, camera_id: str, session_id: str, candidate: Candidate) -> None:
        opened, camera = await self._held(household_id, camera_id)
        await self._adapters[opened.connection.kind].live_candidate(opened, camera, session_id, candidate)
