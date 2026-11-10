"""`tools.home_location`: the household's own location as a person set it, read from People; none when unset; a
household that cannot be read is an unknown location; a household with no house has no fallback."""

import asyncio
from collections.abc import Generator

import pytest
from ashley import services
from ashley.home_assistant.zone import Coordinates, HomeUnknown
from ashley.people.model import Account, Household, Person
from ashley.people.people import People, PeopleUnavailable
from ashley.tools import home_location

HOUSE = Household(1, "home", "UTC", "", (), latitude=51.5072, longitude=-0.1276)
BARE = Household(2, "bare", "UTC", "", ())


class Fixed(People):
    def __init__(self, down: bool = False) -> None:
        self._down = down

    async def household(self, household_id: int) -> Household | None:
        if self._down:
            raise PeopleUnavailable("down")
        return {1: HOUSE, 2: BARE}.get(household_id)

    async def person_for(self, system: str, external_id: str) -> Person | None:
        return None

    async def accounts(self, household_id: int, system: str) -> tuple[Account, ...]:
        return ()


@pytest.fixture(autouse=True)
def _people() -> Generator[None]:
    services.register(People, Fixed())
    yield
    services.unregister(People)


def test_a_household_reads_its_own_location() -> None:
    assert asyncio.run(home_location.own(1)) == Coordinates(51.5072, -0.1276)


@pytest.mark.parametrize("household_id", [2, 99])
def test_a_household_with_none_set_or_no_such_household_has_no_own_location(household_id: int) -> None:
    assert asyncio.run(home_location.own(household_id)) is None


def test_an_unreadable_household_is_an_unknown_location() -> None:
    services.register(People, Fixed(down=True))
    with pytest.raises(HomeUnknown) as e:
        asyncio.run(home_location.own(1))
    assert e.value.reason == "unavailable"


def test_a_household_with_no_house_has_nowhere_else_to_look() -> None:
    with pytest.raises(HomeUnknown) as e:
        asyncio.run(home_location.no_house())
    assert e.value.reason == "no_location"
