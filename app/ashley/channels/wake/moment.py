"""The facts of a house wake's moment for `Initiative` (`ashley.initiative.moment.Moment`), gathered before her turn
starts: the event's hour in the household's zone, how many others are home (`Presence`), and what came before it for
the person (`Wakes.said_before`), each measured back from when the event happened, plus the household's devices at the
place the wake names (`reminder_device.at_place`). So the moment is a function of history, the devices and the event's
time alone. A fact that cannot be read now is None."""

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ... import services
from ...initiative.moment import Moment
from ...people.model import Household, Person
from ...people.people import People
from ...senses.presence import Presence
from ...senses.wakes import Wake, Wakes
from ..devices import Devices
from .reminder_device import at_place


async def gathered(wake_id: int, wake: Wake, person: Person) -> Moment:
    """Raises PeopleUnavailable, WakesUnavailable or DevicesUnavailable, as the runner's other reads do."""
    household, home, said, listed = await asyncio.gather(
        services.get(People).household(wake.household_id), services.get(Presence).home(wake.household_id),
        services.get(Wakes).said_before(wake_id, person.id), services.get(Devices).of_household(wake.household_id))
    return Moment(f"wake:{wake_id}", _hour(wake.at, household), None if home is None else len(home - {person.id}),
                  _since(wake.at, said.heard_at), _since(wake.at, said.greeted_at), _since(wake.at, said.spoke_at),
                  at_place(listed, wake.what))


def _hour(at: datetime, household: Household | None) -> int | None:
    if household is None:
        return None
    try:
        return at.astimezone(ZoneInfo(household.timezone)).hour
    except (ZoneInfoNotFoundError, ValueError):
        return None


def _since(at: datetime, before: datetime | None) -> float | None:
    return None if before is None else (at - before).total_seconds()
