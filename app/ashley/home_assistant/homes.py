"""The Homes service (`ashley.services`): which Home Assistant a household reaches, and its automations there. A
household's HA is its `home_assistant` connection (`ashley.connections`); every caller that touches a house asks with
the household it already holds, so no household reaches another's. `connected_homes.ConnectedHomes` implements it.

Tokens and addresses are never logged; logs carry household ids, reasons and counts."""

from abc import abstractmethod
from dataclasses import dataclass
from typing import Literal

from .. import services
from ..services import Service
from .automations import Automations
from .client import HomeAssistant
from .house import House, NullHouse

SCHEMES = frozenset({"http", "https"})
"""What a household's HA may be reached at: plain http too, since most are served on the household's own network
with no certificate."""

Reason = Literal["refused", "unreachable", "not_home_assistant"]
"""Why a check failed: `refused`, HA turned the token away (401, 403); `unreachable`, no answer in time, a redirect or
a server error; `not_home_assistant`, what answered is not HA's API (404, or a body that is not its JSON)."""


class HomeAssistantFailed(Exception):
    def __init__(self, reason: Reason) -> None:
        super().__init__(reason)
        self.reason: Reason = reason


class HomesUnavailable(Exception):
    """Which HA the household reaches could not be read now (its connections unreadable) and none was known before.
    Transient."""


@dataclass(frozen=True, eq=False)
class Home:
    """One household's Home Assistant: the client for its instance, its automations over that client, and the house as a
    `House`. The same object while the household's connection is unchanged, so what is built on it may be kept with it."""

    household_id: int
    home_assistant: HomeAssistant
    automations: Automations
    house: House


class Homes(Service):
    @classmethod
    def null(cls) -> "Homes":
        return NullHomes()

    @abstractmethod
    async def of(self, household_id: int) -> Home | None:
        """The household's Home Assistant; None when it has none. Raises HomesUnavailable."""

    @abstractmethod
    async def check(self, base_url: str, token: str) -> None:
        """Whether Home Assistant at `base_url` answers its API with `token`: one `GET /api/`, no redirect followed.
        Raises HomeAssistantFailed."""


class NullHomes(Homes):
    """No household reaches a house."""

    async def of(self, household_id: int) -> Home | None:
        return None

    async def check(self, base_url: str, token: str) -> None:
        raise HomeAssistantFailed("unreachable")


async def house_of(household_id: int) -> House:
    """The household's house; the Null Object, which offers nothing and raises, when it has no house or which one
    cannot be read now."""
    try:
        home = await services.get(Homes).of(household_id)
    except HomesUnavailable:
        return NullHouse()
    return NullHouse() if home is None else home.house
