"""A turn a wake starts, moved from the phone thread to the thread of the device its words go to (`device:<id>`), with
the device's audience and place, so what she says is fit for whoever is there: spoken for a satellite (`room`), which
the satellites singleton says (`ashley.channels.voice.reminders`), text for a screen, which its page shows as it does
any turn of its thread (`Inbound.device_id`)."""

from dataclasses import replace

from ...senses.wakes import Route
from ..model import Device, Inbound


def moved(phone: Inbound, route: Route, device: Device) -> Inbound:
    """`phone` as the turn on `device`, which `route` (`room` or `screen`) names."""
    room = route == "room"
    return replace(phone, thread=f"device:{device.id}", medium="spoken" if room else "text", audience=device.audience,
                   shared=True, place=device.place, channel="voice" if room else "web",
                   device_id=None if room else device.id)
