"""Where the house is, for place search, from two sources: the household's own location, set by a person on the
household page, and Home Assistant's `zone.home` (`ashley.home_assistant.zone`). The household's own wins, being the
explicit one, as a row wins over the env. The coordinates are people's data and are never logged."""

from .. import services
from ..home_assistant.zone import Coordinates, HomeUnknown
from ..people.people import People, PeopleUnavailable


async def own(household_id: int) -> Coordinates | None:
    """The location a person of the household set, read fresh; None when none is set. Raises HomeUnknown
    (`unavailable`) when the household cannot be read."""
    try:
        found = await services.get(People).household(household_id)
    except PeopleUnavailable as e:
        raise HomeUnknown("unavailable") from e
    if found is None or found.latitude is None or found.longitude is None:
        return None
    return Coordinates(found.latitude, found.longitude)


async def no_house() -> Coordinates:
    """The `home` source of a household with no Home Assistant. Raises HomeUnknown (`no_location`)."""
    raise HomeUnknown("no_location")
