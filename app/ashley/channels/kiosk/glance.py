"""The hallway tablet's glance: who of the household is home, by first name, and how the household writes its clock.
Who is home is shown to whoever stands in the hallway, which is a house's own knowledge; nothing else about anyone is.
The clock's time is the tablet's own, and calendar and reminders have no source yet, so the routes say so rather than
showing any.

Logs `kiosk.people_unavailable` when the household could not be read; who is home is never logged (Presence logs its
count)."""

import logging
from dataclasses import dataclass

from ... import logs, services
from ...people.model import Clock, Household
from ...people.people import People, PeopleUnavailable
from ...senses.presence import Presence

log = logging.getLogger("ashley.channels.kiosk")


@dataclass(frozen=True)
class Glance:
    """`home` is the names of the household's people who are home, ordered by person id; empty when everyone known is
    away, None when it cannot be known (Presence answered unknown, or the household could not be read). `locale` and
    `clock` are the household's (`Household`), None when it could not be read."""

    home: tuple[str, ...] | None
    locale: str | None
    clock: Clock | None


async def glance(household_id: int) -> Glance:
    try:
        household = await services.get(People).household(household_id)
    except PeopleUnavailable:
        logs.warning(log, "kiosk.people_unavailable", household=household_id)
        return Glance(None, None, None)
    if household is None:
        return Glance(None, None, None)
    return Glance(await _home(household), household.locale, household.clock)


async def _home(household: Household) -> tuple[str, ...] | None:
    present = await services.get(Presence).home(household.id)
    if present is None:
        return None
    return tuple(p.name for p in household.people if p.id in present)
