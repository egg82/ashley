"""Pins on what an install relies on from the house's automations, each added for a mutant that survived the suites
(`automations_house_MUTANTS.txt`): a written automation is waited for until Home Assistant shows it, and an error
answer from HA at any step is a failure naming that step, never taken as done. Run through `carry_out` over the fake
HA, so they hold whichever implementation of the house answers."""

import pytest
from ashley import services
from ashley.workshop.install_piece import NO_ENTITY, PART_WAY, UNREACHABLE, automation_id_for, carry_out
from ashley.workshop.installs import InstallRecord
from ashley.workshop.model import Owner
from ashley.workshop.workshop import Applied, Workshop
from automations_support import FakeHouse
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import household, person, run
from install_support import CONFIG, add, install, propose, world

CONFIG_PATH = "/api/config/automation/config/"


def owner(url: str) -> Owner:
    home = household(url)
    return Owner(home, person(url, home))


async def installed(alana: Owner, enabled: bool = False, turn_off: str | None = None) -> tuple[int, Applied]:
    shop = services.get(Workshop)
    bench = await shop.open(alana, "b")
    await shop.apply(alana, bench.id, add(alana))
    await shop.apply(alana, bench.id, propose(enabled=enabled, turn_off=turn_off))
    return bench.id, await shop.apply(alana, bench.id, install(alana, bench.id, 2))


def ended(record: InstallRecord | None) -> tuple[str | None, str | None]:
    assert record is not None
    return record.ending, record.note


def test_an_automation_home_assistant_shows_only_on_the_last_read_waited_for_is_still_turned_off(db_url: str) -> None:
    alana = owner(db_url)
    house = FakeHouse()

    async def scenario() -> None:
        async with world(db_url, house):
            bench, applied = await installed(alana, enabled=False)
            house.hidden_for = 3
            assert ended(await carry_out(alana, bench, applied)) == ("done", None)
            assert house.enabled == {house.entity_of(automation_id_for(bench, 1)): False}

    run(scenario())


def test_an_automation_home_assistant_never_shows_ends_failed_and_is_not_turned_on_or_off(db_url: str) -> None:
    alana = owner(db_url)
    house = FakeHouse()

    async def scenario() -> None:
        async with world(db_url, house):
            bench, applied = await installed(alana, enabled=False)
            house.hidden_for = 100
            assert ended(await carry_out(alana, bench, applied)) == ("failed", NO_ENTITY)
            ident = automation_id_for(bench, 1)
            assert house.configs[ident] == {"id": ident, **CONFIG}
            assert ("POST", "/api/services/automation/turn_off") not in house.writes

    run(scenario())


@pytest.mark.parametrize("status", [500, 400])
def test_home_assistant_erroring_on_the_turn_off_ends_the_install_failed_from_that_step(db_url: str, status: int) -> None:
    alana = owner(db_url)
    house = FakeHouse(failing={("POST", "/api/services/automation/turn_off"): status})

    async def scenario() -> None:
        async with world(db_url, house):
            bench, applied = await installed(alana, enabled=False)
            assert ended(await carry_out(alana, bench, applied)) == ("failed", PART_WAY.format(step="turn off"))

    run(scenario())


def test_home_assistant_erroring_on_the_config_write_ends_the_install_failed_from_that_step(db_url: str) -> None:
    alana = owner(db_url)
    house = FakeHouse()

    async def scenario() -> None:
        async with world(db_url, house):
            bench, applied = await installed(alana, enabled=True)
            house.failing["POST", CONFIG_PATH + automation_id_for(bench, 1)] = 500
            assert ended(await carry_out(alana, bench, applied)) == ("failed", PART_WAY.format(step="write"))

    run(scenario())


def test_home_assistant_erroring_on_the_read_before_the_install_writes_nothing(db_url: str) -> None:
    alana = owner(db_url)
    house = FakeHouse()

    async def scenario() -> None:
        async with world(db_url, house):
            bench, applied = await installed(alana)
            house.failing["GET", CONFIG_PATH + automation_id_for(bench, 1)] = 500
            assert ended(await carry_out(alana, bench, applied)) == ("failed", UNREACHABLE)
            assert house.writes == []

    run(scenario())
