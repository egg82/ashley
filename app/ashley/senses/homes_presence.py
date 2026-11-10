"""Presence from each household's own Home Assistant (`ashley.home_assistant.homes.Homes`): a household's people are
read on its house as `home_assistant_presence.HomeAssistantPresence` reads them; a household with no house, or one that
cannot be read now, is unknown."""

import logging
import time

from .. import logs, services
from ..home_assistant.homes import Homes, HomesUnavailable
from ..people.people import People
from .home_assistant_presence import HomeAssistantPresence
from .presence import Presence

log = logging.getLogger("ashley.senses")


class HomesPresence(Presence):
    def __init__(self, people: People, timeout_s: float = 5.0) -> None:
        self._people = people
        self._timeout_s = timeout_s

    async def home(self, household_id: int) -> frozenset[int] | None:
        started = time.monotonic()
        try:
            house = await services.get(Homes).of(household_id)
        except HomesUnavailable:
            return _unknown("house_unavailable", started)
        if house is None:
            return _unknown("no_house", started)
        return await HomeAssistantPresence(house.home_assistant, self._people, self._timeout_s).home(household_id)


def _unknown(reason: str, started: float) -> None:
    logs.warning(log, "presence.unknown", reason=reason, duration_ms=int((time.monotonic() - started) * 1000))
