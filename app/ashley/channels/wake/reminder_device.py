"""The device a reminder's `room` or `screen` route names, read from the household's own devices: a room is one of its
satellites, a screen one of its text devices that is neither a satellite, a Discord server nor the house (the kiosk).
Decided by the device's form and medium, never its name."""

from ... import services
from ...senses.wakes import Reminder, Route
from ...tools.tools import ToolsUnavailable
from ..devices import Devices, DevicesUnavailable
from ..model import Listed


def fits(listed: Listed, route: Route) -> bool:
    """Whether `listed` can carry `route`."""
    if route == "room":
        return listed.form == "satellite"
    return route == "screen" and listed.form == "other" and listed.device.medium == "text"


async def takes(household_id: int, route: Route, device_id: int) -> bool:
    """Whether the household's device `device_id` can carry `route`, for `ReminderTools`. Raises ToolsUnavailable when
    the devices cannot be read."""
    try:
        listed = await services.get(Devices).of_household(household_id)
    except DevicesUnavailable as e:
        raise ToolsUnavailable("devices unavailable") from e
    return any(d.device.id == device_id and fits(d, route) for d in listed)


async def of(reminder: Reminder) -> Listed | None:
    """The device `reminder`'s route names when it still exists and fits that route; None for any other route, or when
    it is gone or no longer fits, so the reminder goes to the phone. Raises DevicesUnavailable."""
    if reminder.device_id is None:
        return None
    listed = await services.get(Devices).of_household(reminder.household_id)
    return next((d for d in listed if d.device.id == reminder.device_id and fits(d, reminder.route)), None)
