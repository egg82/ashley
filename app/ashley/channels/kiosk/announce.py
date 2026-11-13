"""The hallway's announcements on the screens someone is looking at: a reply the `Outbox` holds for a screen device's
thread (`device:<id>`, the kiosk, as `ashley.channels.wake.reminder_device.fits` tells a screen), which the satellites
singleton takes with every `device:` reply (`ashley.channels.voice.later`) and hands here rather than to a satellite.

Where it goes (`chosen`), from the screens open on either site with what each last reported
(`ashley.live.screens.Screens.open_screens`) and who is home (`ashley.senses.presence.Presence`): that kiosk, when its
page is in the foreground and someone is home or it cannot be known; and the foregrounded web page of each person known
to be away, which includes a person Presence cannot place. Each chosen screen is sent `ashley.live.events.Announced`
naming one clip (`ashley.channels.voice.clips.Clips`): her voice for the reply, respelled with the household's words,
and the reply as plain text for the screen to show. Nothing is kept for a screen that was not looking."""

from collections.abc import Iterable

from ... import services
from ...live.events import Announced, Shown
from ...live.live import Live, load as live_config
from ...live.screens import OpenScreen, Screens, ScreensUnavailable
from ...senses.presence import Presence
from ..devices import DevicesUnavailable
from ..lexicons import Lexicons
from ..outbox import Later
from ..push.plain import plain_text
from ..voice.clips import Clips, ClipsUnavailable
from ..wake.reminder_device import named

PRESENT_S = live_config().present_s


def chosen(household_id: int, device_id: int, open_screens: Iterable[OpenScreen],
           home: frozenset[int] | None) -> tuple[Shown, ...]:
    """Who an announcement for the kiosk `device_id` is shown to: that kiosk when it is in the foreground and `home`
    (who is home, None when unknown) is not known to be empty; then each person not in a known `home` with a web page
    in the foreground, by id."""
    visible = [s for s in open_screens if s.visible]
    kiosk = home != frozenset() and any(s.device_id == device_id for s in visible)
    away = () if home is None else sorted({s.person_id for s in visible if s.person_id is not None} - home)
    return (*([Shown(household_id, None, device_id)] if kiosk else []), *(Shown(household_id, p) for p in away))


async def is_screen(household_id: int, device_id: int) -> bool:
    """Whether the household's device `device_id` is a screen (the kiosk); False when the devices cannot be read, so the
    reply is dropped as for a satellite not connected."""
    try:
        return await named(household_id, "screen", device_id) is not None
    except DevicesUnavailable:
        return False


async def announce(later: Later, device_id: int) -> tuple[str, int | None, int]:
    """`later`, a reply for the kiosk `device_id`, announced where `chosen` says: how (`screens`, `no_line` for a reply
    with no words, `no_screen` when nobody is looking, `screens_unavailable`, `clips_unavailable`), the clip's id, and
    how many people's and devices' screens it was sent to."""
    line = plain_text(later.outbound.body).strip()
    if not line:
        return "no_line", None, 0
    try:
        open_screens = await services.get(Screens).open_screens(later.household_id, PRESENT_S)
    except ScreensUnavailable:
        return "screens_unavailable", None, 0
    to = chosen(later.household_id, device_id, open_screens, await services.get(Presence).home(later.household_id))
    if not to:
        return "no_screen", None, 0
    spoken = (await services.get(Lexicons).of(later.household_id)).respell(line)
    try:
        clip = await services.get(Clips).add(device_id, spoken, later.age_ms, line)
    except ClipsUnavailable:
        return "clips_unavailable", None, len(to)
    for shown in to:
        services.get(Live).publish(Announced(shown, clip.token))
    return "screens", clip.id, len(to)

