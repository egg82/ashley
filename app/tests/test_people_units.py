"""`people.units.metric_of`: whether a household reads metric, False wherever the household cannot say."""

import asyncio
from dataclasses import dataclass

import pytest
from ashley import services
from ashley.people.model import Account, Household, Person, UnitSystem
from ashley.people.people import People
from ashley.people.units import metric_of


@dataclass
class Home(People):
    home: Household

    async def household(self, household_id: int) -> Household | None:
        return self.home if household_id == self.home.id else None

    async def person_for(self, system: str, external_id: str) -> Person | None:
        return None

    async def accounts(self, household_id: int, system: str) -> tuple[Account, ...]:
        return ()


def wire(units: UnitSystem, household_id: int = 1) -> None:
    people = (Person(1, household_id, "Alana"),)
    services.register(People, Home(Household(household_id, "home", "Europe/London", "", people, unit_system=units)))


@pytest.mark.parametrize(("units", "metric"), [("imperial", False), ("metric", True)])
def test_a_household_reads_the_units_it_set(units: UnitSystem, metric: bool) -> None:
    wire(units)
    assert asyncio.run(metric_of(1)) is metric


def test_an_unknown_household_or_unwired_people_reads_as_written() -> None:
    assert asyncio.run(metric_of(1)) is False
    wire("metric")
    assert asyncio.run(metric_of(2)) is False
