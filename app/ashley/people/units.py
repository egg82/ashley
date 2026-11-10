"""A household's unit system, for the places that show amounts in the units it reads."""

from .. import services
from .people import People, PeopleUnavailable


async def metric_of(household_id: int) -> bool:
    """Whether the household reads metric; False (the amounts as the source wrote them) when people cannot be reached
    or there is no such household."""
    try:
        household = await services.get(People).household(household_id)
    except PeopleUnavailable:
        return False
    return household is not None and household.unit_system == "metric"
