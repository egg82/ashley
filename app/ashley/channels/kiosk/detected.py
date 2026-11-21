"""What a camera's own detector reporting puts on the screens: the first use of a detection (`ashley.cameras.model`).
The watches singleton runs it beside the watches and shadow runs, so one site at a time holds the Home Assistant
sockets it follows the cameras over (`Cameras.follow`). Each pass follows each household's cameras again, so a camera
named or dropped since is followed or let go, and prunes old detections.

A detection acts in code, never in a model: when its class is one of `detection.json`'s `show_feed_on` it is recorded
once (`Detections.claim`, so a pod on each site, or an event told twice, acts once), and unless a feed was shown for that
camera within `min_gap_s` its feed goes where `feed.show` puts one, for every screen device of the household, with
the feed's own auto-clear. A class in `speak_on` is claimed the same way, so the camera's gap and the once-across-both-sites
guarantee hold for it too, and it is stored as a `detection` wake (`Wakes.detected`) with the camera's recordings known
at that moment: her turn on it, with a look at the recording the detector captured, is `ashley.channels.wake.detection_turn`.
Nothing is spoken here.

Logs `camera.detection` (household, a short hash of the camera, class, outcome: `shown`, `no_screen`, `told` for a class
that is only spoken on, `ignored`, `duplicate`, `too_soon`, `unavailable`) and `camera.detection_wake` (household, camera
hash, class, whether the wake was `new`, and how many recordings were known, -1 when they could not be read) and `camera.detection_tick` (households, followed, unreachable, pruned) when
anything was done. Never an entity id or a name."""

import asyncio
import hashlib
import logging
from collections import Counter
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from ... import logs, services
from ...cameras.detection_settings import DetectionSettings, load
from ...cameras.detections import Detections, DetectionsUnavailable
from ...cameras.cameras import Cameras
from ...cameras.model import (CamerasFailed, CamerasUnavailable, Detection, DetectionRecorder, NoSuchCamera,
                              NotConnected)
from ...connections.connections import Connections, ConnectionsUnavailable
from ...connections.kinds import ConnectionKinds
from ...live.screens import ScreensUnavailable
from ...senses.wakes import DetectionWake, Wakes, WakesUnavailable
from ..devices import DevicesUnavailable
from . import feed

log = logging.getLogger("ashley.cameras")
Clock = Callable[[], datetime]


def _now() -> datetime:
    return datetime.now(UTC)


async def run(settings: DetectionSettings | None = None, sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
              clock: Clock = _now) -> None:
    """Pass every `tick_s` until cancelled. Never raises but CancelledError."""
    settings = settings or load()
    watching: set[int] = set()
    while True:
        try:
            await tick(settings, watching, clock)
        except (ConnectionsUnavailable, DetectionsUnavailable):
            logs.warning(log, "camera.detection_unavailable")
        await sleep(settings.tick_s)


async def tick(settings: DetectionSettings, watching: set[int], clock: Clock = _now) -> Counter[str]:
    """One pass: follow (or let go of) the cameras of every household holding a camera connection and of every one
    followed last pass; `watching` is those followed, updated. Raises ConnectionsUnavailable, DetectionsUnavailable."""
    kinds = [k.name for k in services.get(ConnectionKinds).of_port("camera")]
    holding = set(await services.get(Connections).households_of_kinds(kinds))
    counts: Counter[str] = Counter()
    for household in sorted(holding | watching):
        try:
            counts["followed"] += await services.get(Cameras).follow(household, _recorder(household, settings, clock))
        except (CamerasUnavailable, CamerasFailed):
            counts["unreachable"] += 1
            continue
        if household in holding:
            watching.add(household)
        else:
            watching.discard(household)
    counts["households"] = len(holding)
    counts["pruned"] = await services.get(Detections).prune(clock(), settings.keep_s)
    if counts["unreachable"] or counts["pruned"]:
        logs.info(log, "camera.detection_tick", **{k: counts[k] for k in ("households", "followed", "unreachable", "pruned")})
    return counts


def _recorder(household_id: int, settings: DetectionSettings, clock: Clock) -> DetectionRecorder:
    async def heard(detection: Detection) -> None:
        await act(household_id, detection, settings, clock())
    return heard


async def act(household_id: int, detection: Detection, settings: DetectionSettings, now: datetime) -> str:
    """What `detection` does, as its outcome (logged). Never raises for the screens, the devices or the record being
    unreachable: that is `unavailable`, and the detection is lost."""
    outcome = await _decide(household_id, detection, settings, now)
    logs.info(log, "camera.detection", household=household_id, camera=_short(detection.camera_id),
              kind=detection.kind, outcome=outcome)
    return outcome


async def _decide(household_id: int, detection: Detection, settings: DetectionSettings, now: datetime) -> str:
    feeds, speaks = detection.kind in settings.show_feed_on, detection.kind in settings.speak_on
    if not (feeds or speaks):
        return "ignored"
    try:
        claimed = await services.get(Detections).claim(household_id, detection, settings.min_gap_s)
        if claimed != "new":
            return claimed
        shown = feeds and await feed.show(household_id, detection.camera_id, await feed.screens_of(household_id), now) > 0
        if shown:
            await services.get(Detections).shown(household_id, detection)
        if speaks:
            await _told(household_id, detection)
    except (DetectionsUnavailable, ScreensUnavailable, DevicesUnavailable, WakesUnavailable):
        return "unavailable"
    return ("shown" if shown else "no_screen") if feeds else "told"


async def _told(household_id: int, detection: Detection) -> None:
    """Store the wake her turn on `detection` is. Raises WakesUnavailable."""
    known = await _known(household_id, detection.camera_id)
    received = await services.get(Wakes).detected(
        DetectionWake(household_id, detection.camera_id, detection.kind, detection.at, known))
    logs.info(log, "camera.detection_wake", household=household_id, camera=_short(detection.camera_id),
              kind=detection.kind, new=received.new, known=-1 if known is None else len(known))


async def _known(household_id: int, camera_id: str) -> tuple[str, ...] | None:
    """The ids of the camera's recordings now, newest first; None when they cannot be read."""
    try:
        return tuple(r.id for r in await services.get(Cameras).recordings(household_id, camera_id))
    except (CamerasUnavailable, CamerasFailed, NotConnected, NoSuchCamera):
        return None


def _short(camera_id: str) -> str:
    return hashlib.sha256(camera_id.encode()).hexdigest()[:8]
