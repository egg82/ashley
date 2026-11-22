"""A bench machine's webcams behind the Cameras port: one camera per USB webcam its herdr bridge lists
(`GET /v1/cameras`), titled `<connection label>: <device name>` and identified `webcam.<connection id>_<bridge id>`, so
two machines with the same camera in the same port stay two cameras. A camera is listed only when the connection's
`look_cameras` setting names it. A still is one frame the bridge takes with ffmpeg when asked (`GET
/v1/cameras/:id/still`); nothing here polls a camera. A bridge older than 0.6.0 answers 404 to the list, which is no
cameras. A bridge gives no feed this port can pass on, no recordings and no detector, so a live look is `NoLiveFeed` (the source's default)."""

import logging
from datetime import UTC, datetime

from .. import logs, services
from ..cameras import looking
from ..cameras.model import Camera, CamerasFailed, Reason, Still
from ..cameras.source import CameraSource
from ..connections.model import Opened
from . import config
from .bridge import Bridge
from .model import Access, BridgeCamera, BridgeFailed
from .model import Reason as BridgeReason

NAME = "herdr"
LOOK_CAMERAS = looking.LOOK_CAMERAS
DOMAIN = "webcam"
STILL_MAX_BYTES = config.load().response_max_bytes

log = logging.getLogger("ashley.herdr")
_REASON: dict[BridgeReason, Reason] = {"herdr_unavailable": "unreachable", "unconfirmed": "unreachable",
                                       "camera_busy": "unreachable", "camera_failed": "unreachable",
                                       "bad_token": "refused", "wrong_person": "refused"}


def camera_id(connection_id: int, bridge_camera: str) -> str:
    return f"{DOMAIN}.{connection_id}_{bridge_camera}"


def _bridge_id(camera: Camera) -> str:
    return camera.id.removeprefix(f"{DOMAIN}.").partition("_")[2]


def _failed(e: BridgeFailed) -> CamerasFailed:
    return CamerasFailed(_REASON.get(e.reason, "unrecognised"))


def _access(opened: Opened) -> Access:
    person = opened.connection.person_id
    try:
        if person is None:
            raise BridgeFailed("unexpected")
        return Access.of(opened.connection.base_url, opened.secret, person)
    except BridgeFailed as e:
        raise _failed(e) from e


async def _on_bridge(opened: Opened) -> tuple[BridgeCamera, ...]:
    try:
        return await services.get(Bridge).cameras(_access(opened))
    except BridgeFailed as e:
        if e.reason == "not_found":
            return ()
        raise _failed(e) from e


class HerdrCameras(CameraSource):
    async def cameras(self, opened: Opened) -> tuple[Camera, ...]:
        allowed = await looking.allowed(opened)
        on_bridge = await _on_bridge(opened)
        c = opened.connection
        found = tuple(Camera(camera_id(c.id, b.id), f"{c.label}: {b.name}" if c.label else b.name, NAME, c.id)
                      for b in on_bridge if camera_id(c.id, b.id) in allowed)
        logs.info(log, "herdr.cameras", connection=c.id, webcams=len(on_bridge), listed=len(found))
        return found

    async def still(self, opened: Opened, camera: Camera) -> Still | None:
        try:
            data = await services.get(Bridge).camera_still(_access(opened), _bridge_id(camera), STILL_MAX_BYTES)
        except BridgeFailed as e:
            if e.reason == "not_found":
                return None
            raise _failed(e) from e
        return Still(data, "image/jpeg", datetime.now(UTC))
