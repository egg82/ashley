"""The turn a camera's detector event starts (`ashley.channels.kiosk.detected` stores it as a `detection` wake): her own turn,
the household's, addressed to no one (`Inbound.speaker_id` None), on the thread of one of the household's screens, so what she
says is queued in the outbox and `ashley.channels.kiosk.announce` plays it where people are: that kiosk when its page is in
the foreground and someone is home, and the foregrounded web page of each person who is away. Which screen is the household's
kiosk whose page is in the foreground, else the first by id.

She is told the detector's class and time and the camera's title, and, when the camera's recordings (`Cameras.recordings`) now
hold one that was not there when the event was heard, begins with having looked at it (`Inbound.seen`,
`ashley.channels.seen`): she says what that picture shows. A class of `look_now_on` begins with the camera's view now instead,
waiting for nothing. A recording that has not appeared leaves the wake due, until
`detection.json`'s `look_wait_s` has passed since the event was stored, then she is told no picture could be had and to say
she could not see; the same when the recordings were unreadable at the event. Which recording is new is decided by ids, never
by a title. Her tools are `camera_look` alone, since her look is in the turn as a call of it.

Whether it goes out is Initiative's: the turn has no moment, so it goes out on her `says`, and nothing goes out while every
person of the household is within their own quiet hours at the event's time (`Inbound.quiet`), except for a class in
`detection.json`'s `speak_in_quiet_on` (a ring), which is never held and does not ask People; a household with no people is
never quiet. A wake past `max_age_s`, with the camera gone from the household's list or its connection, or with no screen
to say it on, is settled without a turn. The wake's id is the turn's `source`, so a wake handed in twice is one turn.

Logs `detection_wake.done` with the wake id, the class, whether she began with a look (`seen`) and duration_ms;
`detection_wake.refused` with the wake id. Never a camera, a title or a picture."""

import logging
import time

from ... import logs, services
from ...cameras.cameras import Cameras
from ...cameras.detection_settings import load
from ...cameras.model import CamerasFailed, NoSuchCamera, NotConnected
from ...live.screens import Screens
from ...people.people import People
from ...people.quiet import held
from ...senses.wakes import DetectionWake, Outcome
from ...tools.camera_specs import LOOK
from ..devices import Devices
from ..kiosk.announce import PRESENT_S
from ..model import Device, Inbound
from ..respond import RespondRefused, respond
from .config import CONFIG
from .reminder_device import fits

log = logging.getLogger("ashley.channels.wake")
WAIT_S = load().look_wait_s
NOW = load().look_now_on
ALWAYS = load().speak_in_quiet_on


class Waiting(Exception):
    """The recording the detector captured has not appeared yet and the wait is not over: the wake stays due."""


def said(wake: DetectionWake) -> str:
    """The wake as the page shows it, from its fields alone."""
    return f"A camera's detector reported: {wake.kind}"


def note(wake: DetectionWake, device: Device, title: str | None) -> str:
    """What only she reads, with the turn."""
    where = "" if title is None else f", the camera {title}"
    looked = ("If a camera_look result in this turn shows what the detector captured, or the camera as it is now, say only what that picture "
              "shows. If there is none, or it says it failed, say that you could not see, and do not guess what it shows "
              "or who it is.")
    return (f"A camera's own detector reported `{wake.kind}` at {wake.at.isoformat(timespec='minutes')}{where}. {looked}\n"
            f"Say in one short line what happened and where, as it is said aloud and shown on the screens in the "
            f"{device.place}, where whoever is near may hear it: say nothing private. It is said only if you set `says` to reply.")


def inbound(wake_id: int, wake: DetectionWake, device: Device, title: str | None, seen: tuple[str, str | None] | None,
            quiet: bool) -> Inbound:
    """The turn on `device`'s thread, with her look at the recording `seen` names when there is one."""
    return Inbound(household_id=wake.household_id, thread=f"device:{device.id}", text=said(wake), kind="chat", medium="text",
                   audience=device.audience, speaker_id=None, shared=True, place=device.place, channel="web",
                   remembers=False, later=True, later_by="outbox", device_id=device.id, source=f"wake:{wake_id}",
                   unprompted=True, author="household", note=note(wake, device, title),
                   tools_only=(LOOK,), taint=None, quiet=quiet, seen=seen)


async def fired(wake_id: int, wake: DetectionWake, age_s: float) -> Outcome:
    """What came of it: `turn`, `expired` past `max_age_s`, `cancelled` when the camera is no longer one she may look
    through or no screen can carry it, `failed` when the model refused it. Raises Waiting, and CamerasUnavailable,
    DevicesUnavailable, ScreensUnavailable, PeopleUnavailable and RespondUnavailable, which leave it due."""
    if age_s > CONFIG.max_age_s:
        return "expired"
    started = time.perf_counter()
    try:
        seen = await _seen(wake, age_s)
        title = await _title(wake)
    except (NoSuchCamera, NotConnected):
        return "cancelled"
    device = await _screen(wake.household_id)
    if device is None:
        return "cancelled"
    try:
        await respond(inbound(wake_id, wake, device, title, seen, await _quiet(wake)))
    except RespondRefused:
        logs.warning(log, "detection_wake.refused", wake=wake_id)
        return "failed"
    logs.info(log, "detection_wake.done", wake=wake_id, kind=wake.kind, seen=seen is not None,
              duration_ms=int((time.perf_counter() - started) * 1000))
    return "turn"


async def _seen(wake: DetectionWake, age_s: float) -> tuple[str, str | None] | None:
    """What she begins by looking at: the camera's view now for a class of `look_now_on`, else the camera and its newest
    recording not there when the event was heard; None when none is to be had. Raises Waiting, NoSuchCamera, NotConnected,
    CamerasUnavailable."""
    if wake.kind in NOW:
        return wake.camera_id, None
    fresh = await _recording(wake, age_s)
    return None if fresh is None else (wake.camera_id, fresh)


async def _recording(wake: DetectionWake, age_s: float) -> str | None:
    """The id of the camera's newest recording that was not there when the event was heard; None when none is to be had.
    Raises Waiting, NoSuchCamera, NotConnected, CamerasUnavailable."""
    if wake.known is None:
        return None
    try:
        found = await services.get(Cameras).recordings(wake.household_id, wake.camera_id)
    except CamerasFailed:
        found = ()
    fresh = next((r.id for r in found if r.id not in wake.known), None)
    if fresh is None and age_s < WAIT_S:
        raise Waiting
    return fresh


async def _title(wake: DetectionWake) -> str | None:
    """The camera's title as its source gives it; None when the roster cannot be read. Raises NotConnected, CamerasUnavailable."""
    try:
        roster = await services.get(Cameras).roster(wake.household_id)
    except CamerasFailed:
        return None
    return next((c.title for c in roster.cameras if c.id == wake.camera_id), None)


async def _screen(household_id: int) -> Device | None:
    """The household's screen whose page is in the foreground, else the first by id; None when it has none.
    Raises DevicesUnavailable, ScreensUnavailable."""
    screens = sorted((d.device for d in await services.get(Devices).of_household(household_id) if fits(d, "screen")),
                     key=lambda d: d.id)
    if not screens:
        return None
    open_screens = await services.get(Screens).open_screens(household_id, PRESENT_S)
    visible = {s.device_id for s in open_screens if s.visible and s.device_id is not None}
    return next((d for d in screens if d.id in visible), screens[0])


async def _quiet(wake: DetectionWake) -> bool:
    """Whether the wake is held: every person of the household within their own quiet hours at its time, unless its class
    is in `speak_in_quiet_on`. Raises PeopleUnavailable."""
    if wake.kind in ALWAYS:
        return False
    found = await services.get(People).household(wake.household_id)
    return found is not None and bool(found.people) and all(held(p, wake.at) for p in found.people)
