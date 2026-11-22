"""Bambuddy's printer cameras behind the Cameras port: one camera per printer it knows (`GET /api/v1/printers/`), titled
as Bambuddy names it and identified `printer.<id>`, listed only when the connection's `look_cameras` setting names it. A
still is Bambuddy's own snapshot (`GET /api/v1/printers/:id/camera/snapshot`), which with Bambuddy's login on needs a
stream token minted first (`POST /api/v1/printers/camera/stream-token`); the token is used once and never kept or
logged. A printer's recordings are the timelapses of its print archives (`GET /api/v1/archives/?printer_id=`, those with a
`timelapse_path`, newest first), and a recording's picture is the middle of three frames Bambuddy cuts from the video
(`GET /api/v1/archives/:id/timelapse/thumbnails`), taken with no time stated. Bambuddy gives a printer camera no live
feed this port can pass on (its stream is motion JPEG), so a live look is `NoLiveFeed`. A printer's detector is its print
failing: an archive whose `status` is `failed` (Bambuddy's own word, which is the detection's class), at its `completed_at`.
Each `follow` pass, which the detection singleton makes every `tick_s`, reads the listed printers' archives and tells the
failures that ended within `detection.json`'s `failure_lookback_s`; the Detections record keeps one told twice from acting twice. Nothing here
retries."""

import base64
import binascii
import logging
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, datetime, timedelta

from .. import logs
from ..cameras import looking as look
from ..cameras.detection_settings import load
from ..cameras.model import (Camera, CamerasFailed, CamerasUnavailable, Candidate, Detection, DetectionRecorder, LiveConfig, LiveSignal, NoLiveFeed,
                             NotConnected, Reason, Recording, Still)
from ..cameras.source import CameraSource
from ..connections.model import Opened
from . import wire
from .client import Reason as BambuddyReason
from .read import Reader

NAME = "bambuddy"
LOOK_CAMERAS = look.LOOK_CAMERAS
DOMAIN = "printer"
ARCHIVES_SEEN = 50
FRAMES = 3
WIDTH = 320
FAILED = "failed"
LOOKBACK = timedelta(seconds=load().failure_lookback_s)

log = logging.getLogger("ashley.bambuddy")
_REASON: dict[BambuddyReason, Reason] = {"refused": "refused", "unreachable": "unreachable",
                                         "not_bambuddy": "unrecognised", "not_found": "unrecognised",
                                         "rejected": "unrecognised"}
_READER = Reader("camera", CamerasUnavailable, NotConnected, lambda r: CamerasFailed(_REASON[r]))


def camera_id(printer_id: int) -> str:
    return f"{DOMAIN}.{printer_id}"


def _printer_of(camera: Camera) -> int:
    return int(camera.id.removeprefix(f"{DOMAIN}."))


class BambuddyCameras(CameraSource):
    async def cameras(self, opened: Opened) -> tuple[Camera, ...]:
        allowed = await look.allowed(opened)
        listed = await _READER.get(opened, "/api/v1/printers/", {}, wire.Printers)
        if listed is None:
            raise CamerasFailed("unrecognised")
        found = tuple(Camera(camera_id(p.id), p.name, NAME, opened.connection.id) for p in listed.root
                      if camera_id(p.id) in allowed)
        logs.info(log, "bambuddy.cameras", connection=opened.connection.id, printers=len(listed.root), listed=len(found))
        return found

    async def still(self, opened: Opened, camera: Camera) -> Still | None:
        minted = await _READER.post(opened, "/api/v1/printers/camera/stream-token", {}, wire.StreamToken)
        if isinstance(minted, str):
            raise CamerasFailed("unrecognised")
        got = await _READER.fetch(opened, f"/api/v1/printers/{_printer_of(camera)}/camera/snapshot",
                                  {"token": minted.token})
        if got is None:
            raise CamerasFailed("unrecognised")
        return Still(got.data, got.media_type, datetime.now(UTC))

    async def recordings(self, opened: Opened, camera: Camera) -> tuple[Recording, ...]:
        return tuple(Recording(str(a.id), camera.id, a.print_name or a.filename)
                     for a in await _timelapses(opened, camera))

    async def recording_still(self, opened: Opened, camera: Camera, recording_id: str) -> Still | None:
        held = next((a for a in await _timelapses(opened, camera) if str(a.id) == recording_id), None)
        if held is None:
            return None
        got = await _READER.get(opened, f"/api/v1/archives/{held.id}/timelapse/thumbnails",
                                {"count": FRAMES, "width": WIDTH}, wire.Thumbnails)
        if got is None or not got.thumbnails:
            return None
        try:
            data = base64.b64decode(got.thumbnails[len(got.thumbnails) // 2], validate=True)
        except binascii.Error as e:
            raise CamerasFailed("unrecognised") from e
        return Still(data, "image/jpeg", None, held.print_name or held.filename)

    async def follow(self, opened: Opened, record: DetectionRecorder) -> int:
        listed = await self.cameras(opened)
        since = datetime.now(UTC) - LOOKBACK
        for camera in listed:
            for archive in await _archives(opened, camera):
                at = _ended(archive)
                if archive.status == FAILED and at is not None and at >= since:
                    await record(Detection(camera.id, archive.status, at))
        return len(listed)

    async def live_config(self, opened: Opened, camera: Camera) -> LiveConfig:
        raise NoLiveFeed

    def live(self, opened: Opened, camera: Camera, offer: str) -> AbstractAsyncContextManager[AsyncIterator[LiveSignal]]:
        return _no_feed()

    async def live_candidate(self, opened: Opened, camera: Camera, session_id: str, candidate: Candidate) -> None:
        raise NoLiveFeed


@asynccontextmanager
async def _no_feed() -> AsyncGenerator[AsyncIterator[LiveSignal]]:
    raise NoLiveFeed
    yield _empty()


async def _empty() -> AsyncIterator[LiveSignal]:
    return
    yield


async def _archives(opened: Opened, camera: Camera) -> list[wire.Archive]:
    got = await _READER.get(opened, "/api/v1/archives/", {"printer_id": _printer_of(camera), "limit": ARCHIVES_SEEN},
                            wire.Archives)
    if got is None:
        raise CamerasFailed("unrecognised")
    return got.root


async def _timelapses(opened: Opened, camera: Camera) -> list[wire.Archive]:
    return [a for a in await _archives(opened, camera) if a.timelapse_path]


def _ended(archive: wire.Archive) -> datetime | None:
    at = archive.completed_at
    return None if at is None else at.replace(tzinfo=UTC) if at.tzinfo is None else at.astimezone(UTC)
