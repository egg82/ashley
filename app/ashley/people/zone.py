"""A household's time zone, for the places that show it when something happened."""

from zoneinfo import ZoneInfo

from .. import services
from .people import People, PeopleUnavailable


async def zone_of(household_id: int) -> ZoneInfo | None:
    """The household's zone; None when people cannot be reached or there is no such household, so a caller leaves its
    times out rather than showing them in a zone it guessed."""
    try:
        household = await services.get(People).household(household_id)
    except PeopleUnavailable:
        return None
    return None if household is None else ZoneInfo(household.timezone)
