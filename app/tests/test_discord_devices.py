"""A device as a household's Discord server with a home channel: `set_discord_server` (and the CLI's `discord` command)
gives an unrevoked device a guild and a home channel, refusing a guild another unrevoked device holds; a revoked
device's guild is free again; `Devices.discord_servers` lists every household's unrevoked server devices in device-id
order with the device's own fields; the Null Object and a dead database raise DevicesUnavailable."""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import psycopg
import pytest
from ashley import services
from ashley.channels.devices import Devices, DevicesUnavailable
from ashley.channels.devices.__main__ import main
from ashley.channels.model import Device, DiscordServer
from ashley.channels.postgres_devices import PostgresDevices
from ashley.db.pool import PoolDatabase
from contract.contract_support import unreachable_conninfo
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import household, run
from discord_support import device_row, execute

BIG = 1_234_567_890_123_456_789      # a real snowflake does not fit 32 bits


@asynccontextmanager
async def store(url: str, connect_timeout_s: float = 5.0) -> AsyncGenerator[PostgresDevices]:
    database = PoolDatabase(url, connect_timeout_s=connect_timeout_s)
    await database.open()
    try:
        yield PostgresDevices(database)
    finally:
        await database.close()


def listed(url: str) -> list[DiscordServer]:
    found: list[list[DiscordServer]] = []

    async def scenario() -> None:
        async with store(url) as devices:
            found.append(await devices.discord_servers())

    run(scenario())
    return found[0]


def pairs(url: str) -> list[tuple[int, int, int]]:
    """(device id, guild id, home channel id) of every listed server."""
    return [(s.device.id, s.guild_id, s.home_channel_id) for s in listed(url)]


async def set_server(url: str, device_id: int, guild_id: int, home_channel_id: int) -> bool:
    async with store(url) as devices:
        return await devices.set_discord_server(device_id, guild_id, home_channel_id)


def server_device(url: str, household_id: int, guild_id: int, name: str, home_channel_id: int = 1) -> int:
    made = device_row(url, household_id, name)
    assert asyncio.run(set_server(url, made, guild_id, home_channel_id)) is True
    return made


def revoke(url: str, device_id: int) -> None:
    execute(url, "UPDATE devices SET revoked_at = now() WHERE id = %s", (device_id,))


def cli(url: str, monkeypatch: pytest.MonkeyPatch, *argv: str) -> int:
    monkeypatch.setenv("DATABASE_URL", url)
    return main(list(argv))


def test_a_server_device_lists_with_every_field_and_a_plain_device_does_not(db_url: str) -> None:
    home = household(db_url)
    device_row(db_url, home, "hallway tablet", "hallway")
    assert listed(db_url) == [], "control: a plain device is no server"
    made = device_row(db_url, home, "family room", "den", kind="brainstorm")
    execute(db_url, "UPDATE devices SET remembers = false WHERE id = %s", (made,))
    assert asyncio.run(set_server(db_url, made, BIG, BIG + 1)) is True
    assert listed(db_url) == [DiscordServer(
        Device(made, home, "family room", "den", "household", "text", "brainstorm", remembers=False), BIG, BIG + 1)]


def test_servers_span_households_are_ordered_by_device_id_and_skip_revoked_devices(db_url: str) -> None:
    one, two = household(db_url, "one"), household(db_url, "two")
    first = server_device(db_url, two, 300, "a", 31)
    second = server_device(db_url, one, 100, "b", 11)
    gone = server_device(db_url, one, 200, "gone", 21)
    revoke(db_url, gone)
    assert [(s.device.id, s.device.household_id, s.guild_id, s.home_channel_id) for s in listed(db_url)] == [
        (first, two, 300, 31), (second, one, 100, 11)]


def test_setting_a_server_again_changes_both_ids_and_the_same_ones_again_is_fine(db_url: str) -> None:
    made = server_device(db_url, household(db_url), 100, "family", 10)
    assert asyncio.run(set_server(db_url, made, 100, 11)) is True, "a new home channel in the same server"
    assert pairs(db_url) == [(made, 100, 11)]
    assert asyncio.run(set_server(db_url, made, 200, 21)) is True
    assert asyncio.run(set_server(db_url, made, 200, 21)) is True
    assert pairs(db_url) == [(made, 200, 21)]


def test_an_unknown_or_revoked_device_cannot_become_a_server(db_url: str) -> None:
    made = device_row(db_url, household(db_url), "family")
    assert asyncio.run(set_server(db_url, 9999, 100, 1)) is False
    revoke(db_url, made)
    assert asyncio.run(set_server(db_url, made, 100, 1)) is False
    assert listed(db_url) == []


def test_a_second_unrevoked_device_cannot_take_a_server_and_both_stay_as_they_were(db_url: str) -> None:
    home = household(db_url)
    holder = server_device(db_url, home, 100, "first", 10)
    other = device_row(db_url, home, "second")
    for home_channel in (10, 99):
        with pytest.raises(psycopg.errors.UniqueViolation):
            asyncio.run(set_server(db_url, other, 100, home_channel))
    assert pairs(db_url) == [(holder, 100, 10)]
    assert asyncio.run(set_server(db_url, other, 101, 10)) is True, "control: a free guild is accepted"


def test_a_revoked_devices_server_can_be_given_to_another_device(db_url: str) -> None:
    home = household(db_url)
    old = server_device(db_url, home, 100, "old", 10)
    new = device_row(db_url, home, "new")
    revoke(db_url, old)
    assert asyncio.run(set_server(db_url, new, 100, 12)) is True
    assert pairs(db_url) == [(new, 100, 12)]


def test_the_cli_sets_a_server_and_reports_an_unknown_device(db_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    made = device_row(db_url, household(db_url), "family")
    assert cli(db_url, monkeypatch, "discord", str(made), str(BIG), str(BIG + 1)) == 0
    assert pairs(db_url) == [(made, BIG, BIG + 1)]
    assert cli(db_url, monkeypatch, "discord", "9999", "5", "6") == 1
    assert cli(db_url, monkeypatch, "revoke", str(made)) == 0
    assert cli(db_url, monkeypatch, "discord", str(made), "7", "8") == 1


def test_the_cli_needs_both_ids(db_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    made = device_row(db_url, household(db_url), "family")
    with pytest.raises(SystemExit) as caught:
        cli(db_url, monkeypatch, "discord", str(made), "100")
    assert caught.value.code == 2 and listed(db_url) == []


def test_the_cli_frees_a_revoked_devices_server_for_another_device(db_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    home = household(db_url)
    old = server_device(db_url, home, 100, "old", 10)
    new = device_row(db_url, home, "new")
    assert cli(db_url, monkeypatch, "discord", str(new), "100", "10") != 0, "control: taken while the holder lives"
    assert cli(db_url, monkeypatch, "revoke", str(old)) == 0
    assert cli(db_url, monkeypatch, "discord", str(new), "100", "10") == 0
    assert pairs(db_url) == [(new, 100, 10)]


def test_the_null_object_has_no_servers_to_give() -> None:
    services.unregister(Devices)
    async def scenario() -> None:
        await services.get(Devices).discord_servers()

    with pytest.raises(DevicesUnavailable):
        run(scenario())


def test_an_unreachable_database_raises_unavailable() -> None:
    async def scenario() -> None:
        async with store(unreachable_conninfo(), connect_timeout_s=0.1) as devices:
            with pytest.raises(DevicesUnavailable):
                await devices.discord_servers()

    run(scenario())
