"""Whether a person's own quiet hours hold at a moment (`decisions.md`, "A person's quiet hours hold back what she says
on her own"). Pure: the same hours and instant always answer the same."""

from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .. import services
from .model import QuietHours, Person
from .people import People


def holds(quiet: QuietHours | None, at: datetime) -> bool | None:
    """Whether `at`, an aware instant, falls inside `quiet`; False for none set; None when the zone cannot be read,
    which is unknown, never a value."""
    if quiet is None:
        return False
    try:
        hour = at.astimezone(ZoneInfo(quiet.timezone)).hour
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return None
    start, end = quiet.start, quiet.end
    return start <= hour < end if start < end else hour >= start or hour < end


def held(person: Person, at: datetime) -> bool:
    """Whether `person`'s own quiet hours hold at `at`; True when their zone cannot be read, so a turn for them stays
    quiet rather than guessing."""
    return holds(person.quiet, at) is not False


async def held_now(household_id: int, person_id: int, at: datetime) -> bool:
    """`held` for the person of that household with that id, read from `People`; False when there is no such person.
    Raises PeopleUnavailable."""
    found = await services.get(People).household(household_id)
    person = None if found is None else next((p for p in found.people if p.id == person_id), None)
    return person is not None and held(person, at)
