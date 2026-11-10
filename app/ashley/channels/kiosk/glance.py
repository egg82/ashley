"""Who of the household is home, by first name, for the hallway tablet's glance. Who is home is shown to whoever stands
in the hallway, which is a house's own knowledge; nothing else about anyone is. The clock is the tablet's own, and
calendar and reminders have no source yet, so the routes say so rather than showing any.

Logs `kiosk.people_unavailable` when the household could not be read; who is home is never logged (Presence logs its
count)."""

import logging

from ... import logs, services
from ...people.people import People, PeopleUnavailable
from ...senses.presence import Presence

log = logging.getLogger("ashley.channels.kiosk")


async def home_names(household_id: int) -> tuple[str, ...] | None:
    """The names of the household's people who are home, ordered by person id; empty when everyone known is away, None
    when it cannot be known (Presence answered unknown, or the household could not be read)."""
    try:
        household = await services.get(People).household(household_id)
    except PeopleUnavailable:
        logs.warning(log, "kiosk.people_unavailable", household=household_id)
        return None
    if household is None:
        return None
    present = await services.get(Presence).home(household_id)
    if present is None:
        return None
    return tuple(p.name for p in household.people if p.id in present)
