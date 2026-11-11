"""Whether lights are on, for the buttons of touch controls that toggle one. Read from the household's house when the
controls are read; a light the house cannot say is left out, so its button shows nothing rather than a guess.

Logs `kiosk.house_unavailable` with the household id when the house could not be read."""

import logging
from collections.abc import Iterable

from .. import logs, services
from ..home_assistant.homes import Homes, HomesUnavailable
from ..home_assistant.house import HouseUnavailable

log = logging.getLogger("ashley.tools")


async def lights_on(household_id: int, entity_ids: Iterable[str]) -> dict[str, bool]:
    """Whether each of `entity_ids` is on, for those the house says are on or off; empty when there is no house or it
    cannot be read."""
    wanted = set(entity_ids)
    if not wanted:
        return {}
    try:
        home = await services.get(Homes).of(household_id)
        if home is None:
            return {}
        states = await home.house.states()
    except (HomesUnavailable, HouseUnavailable):
        logs.warning(log, "kiosk.house_unavailable", household=household_id)
        return {}
    return {s.id: s.state == "on" for s in states if s.id in wanted and s.state in ("on", "off")}
