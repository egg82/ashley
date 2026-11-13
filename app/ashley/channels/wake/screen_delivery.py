"""Fired reminders routed to a screen (the kiosk), tried by the push singleton (`ashley.channels.push.later.drain`). Her
turn is already on the device's thread, which its page shows (`reminder_turn`); a try asks whether a screen of that
device is open on either site (`ashley.live.screens.Screens.showing`), so a screen switched off sends the reminder on
to the phone after its tries (`device_delivery`). `how` in the log is `showing`, `not_showing` or `unknown`."""

from ... import services
from ...conversations.model import Turn
from ...live.live import load as live_config
from ...live.screens import Screens, ScreensUnavailable
from ...senses.wakes import Delivery
from . import device_delivery

PRESENT_S = live_config().present_s


async def deliver() -> int:
    """Try each fired reminder whose next try is at its screen; how many were tried."""
    return await device_delivery.deliver("screen", _shown)


async def _shown(delivery: Delivery, answer: Turn) -> tuple[bool, str]:
    if delivery.device_id is None:
        return False, "unknown"
    try:
        showing = await services.get(Screens).showing(delivery.device_id, PRESENT_S)
    except ScreensUnavailable:
        return False, "unknown"
    return showing, "showing" if showing else "not_showing"
