"""Whether a household's Home Assistant lists an entity, for a rule that names one (`ashley.channels.wake.speaker`)."""

from .. import services
from ..home_assistant.homes import Homes, HomesUnavailable
from ..home_assistant.house import HouseUnavailable


class HouseUnreadable(Exception):
    """The household's house could not be read now. Transient."""


async def lists(household_id: int, entity_id: str) -> bool:
    """Whether the household's house lists `entity_id`; False when it has no house. Raises HouseUnreadable."""
    try:
        home = await services.get(Homes).of(household_id)
        return home is not None and any(s.id == entity_id for s in await home.house.states())
    except (HomesUnavailable, HouseUnavailable) as e:
        raise HouseUnreadable(type(e).__name__) from e
