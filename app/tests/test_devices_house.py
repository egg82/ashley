"""The house's device, over a real database: `set_house` marks an unrevoked device as the household's Home Assistant,
so it lists as form `house`, the one form that may hand in wakes; a satellite or a Discord server cannot also be the
house, and a revoked or unknown device is not found."""

import asyncio

import psycopg
import pytest
from ashley.channels.postgres_devices import PostgresDevices
from ashley.db.pool import PoolDatabase
from contract.conversations_support import db_url as db_url, household, migrated_template as migrated_template
from contract.conversations_support import scalar
from test_devices_list import device, discord, satellite


def set_house(url: str, device_id: int) -> bool:
    async def scenario() -> bool:
        database = PoolDatabase(url)
        await database.open()
        try:
            return await PostgresDevices(database).set_house(device_id)
        finally:
            await database.close()

    return asyncio.run(scenario())


def forms(url: str, household_id: int) -> dict[int, str]:
    async def scenario() -> dict[int, str]:
        database = PoolDatabase(url)
        await database.open()
        try:
            return {d.device.id: d.form for d in await PostgresDevices(database).of_household(household_id)}
        finally:
            await database.close()

    return asyncio.run(scenario())


def test_a_device_set_as_the_house_lists_as_form_house(db_url: str) -> None:
    home = household(db_url)
    house, other = device(db_url, home, "home assistant"), device(db_url, home, "tablet")
    assert set_house(db_url, house)
    assert forms(db_url, home) == {house: "house", other: "other"}


def test_an_unknown_or_revoked_device_is_not_found(db_url: str) -> None:
    home = household(db_url)
    gone = device(db_url, home, "old")
    scalar(db_url, "UPDATE devices SET revoked_at = now() WHERE id = %s RETURNING id", (gone,))
    assert not set_house(db_url, gone) and not set_house(db_url, 99999)


def test_a_satellite_or_a_discord_server_cannot_be_the_house(db_url: str) -> None:
    home = household(db_url)
    for made in (satellite(db_url, home, "kitchen"), discord(db_url, home, "server", 41)):
        with pytest.raises(psycopg.errors.CheckViolation):
            set_house(db_url, made)
