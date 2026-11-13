"""Discord servers as devices: the CLI's `discord` command sets a device's server and home channel, one unrevoked
device per server, and `Devices.discord_servers` lists every household's unrevoked ones; the claims table keeps each message once; and the
settings and wiring that start the singleton."""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import TypeVar

import psycopg
import pytest
from ashley import services
from ashley.channels.devices import Devices, DevicesUnavailable
from ashley.channels.devices.__main__ import main
from ashley.channels.discord.postgres_seen import PostgresSeen
from ashley.channels.model import DiscordServer
from ashley.channels.postgres_devices import PostgresDevices
from ashley.db.pool import PoolDatabase
from ashley.settings import Settings, from_env
from ashley.wiring_singletons import singletons
from contract.conversations_support import db_url as db_url, household
from contract.conversations_support import migrated_template as migrated_template, scalar

T = TypeVar("T")


def against(url: str, call: Callable[[PoolDatabase], Awaitable[T]]) -> T:
    found: list[T] = []

    async def scenario() -> None:
        database = PoolDatabase(url)
        await database.open()
        try:
            found.append(await call(database))
        finally:
            await database.close()

    asyncio.run(scenario())
    return found[0]


def servers(url: str) -> list[DiscordServer]:
    return against(url, lambda database: PostgresDevices(database).discord_servers())


def cli(url: str, monkeypatch: pytest.MonkeyPatch, *argv: str) -> int:
    monkeypatch.setenv("DATABASE_URL", url)
    return main(list(argv))


def device(url: str, household_id: int, name: str) -> int:
    return int(scalar(url, "INSERT INTO devices (household_id, name, place, audience, medium, kind, token_sha256) "
                           "VALUES (%s, %s, 'discord', 'household', 'text', 'chat', sha256(%s::bytea)) RETURNING id",
                      (household_id, name, name.encode())))


def test_the_cli_makes_a_device_a_discord_server_and_changes_it(
        db_url: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    home = household(db_url)
    general = device(db_url, home, "general")
    assert servers(db_url) == [], "control: a plain device is no server"
    assert cli(db_url, monkeypatch, "discord", str(general), "1234567890123", "555") == 0
    [got] = servers(db_url)
    assert (got.device.id, got.device.household_id, got.device.audience, got.guild_id, got.home_channel_id) == (
        general, home, "household", 1234567890123, 555)
    assert cli(db_url, monkeypatch, "discord", str(general), "42", "43") == 0
    assert [(s.guild_id, s.home_channel_id) for s in servers(db_url)] == [(42, 43)]
    assert f"device {general} is Discord server 42, home channel 43" in capsys.readouterr().out


def test_a_server_belongs_to_one_unrevoked_device(db_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    home = household(db_url)
    first, second, third = device(db_url, home, "a"), device(db_url, home, "b"), device(db_url, home, "c")
    assert cli(db_url, monkeypatch, "discord", str(first), "7", "70") == 0
    assert cli(db_url, monkeypatch, "discord", str(second), "7", "71") == 1
    assert [(s.device.id, s.guild_id) for s in servers(db_url)] == [(first, 7)]
    assert cli(db_url, monkeypatch, "revoke", str(first)) == 0
    assert cli(db_url, monkeypatch, "discord", str(third), "7", "70") == 0, "revoking frees the server"
    assert [(s.device.id, s.guild_id) for s in servers(db_url)] == [(third, 7)]


@pytest.mark.parametrize("ids", [("0", "5"), ("5", "-5")])
def test_the_cli_refuses_ids_that_are_not_discord_ids(db_url: str, monkeypatch: pytest.MonkeyPatch,
                                                      ids: tuple[str, str]) -> None:
    general = device(db_url, household(db_url), "general")
    assert cli(db_url, monkeypatch, "discord", str(general), *ids) == 2
    assert servers(db_url) == []


def test_the_schema_refuses_half_a_server(db_url: str) -> None:
    general = device(db_url, household(db_url), "general")
    for half in ("discord_guild_id = 5", "discord_home_channel_id = 5"):
        with pytest.raises(psycopg.errors.CheckViolation, match="devices_discord_server_is_whole"):
            scalar(db_url, f"UPDATE devices SET {half} WHERE id = %s RETURNING id", (general,))


def test_an_unknown_or_revoked_device_cannot_become_a_server(db_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    general = device(db_url, household(db_url), "general")
    assert cli(db_url, monkeypatch, "discord", "999", "7", "8") == 1
    assert cli(db_url, monkeypatch, "revoke", str(general)) == 0
    assert cli(db_url, monkeypatch, "discord", str(general), "7", "8") == 1


def test_servers_span_households_skip_revoked_and_plain_devices_and_are_ordered(
        db_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    first, second = household(db_url, "one"), household(db_url, "two")
    a, b = device(db_url, second, "a"), device(db_url, first, "b")
    device(db_url, first, "plain")
    gone = device(db_url, first, "gone")
    for d, guild in ((a, 1), (b, 2), (gone, 3)):
        assert cli(db_url, monkeypatch, "discord", str(d), str(guild), str(guild * 10)) == 0
    assert cli(db_url, monkeypatch, "revoke", str(gone)) == 0
    assert [(s.device.id, s.device.household_id, s.guild_id) for s in servers(db_url)] == [(a, second, 1),
                                                                                           (b, first, 2)]


def test_the_null_devices_has_no_servers_to_give() -> None:
    services.unregister(Devices)
    with pytest.raises(DevicesUnavailable):
        asyncio.run(services.get(Devices).discord_servers())


def test_a_claim_lands_once_and_last_and_prune_follow_the_claim_time(db_url: str) -> None:
    async def scenario(database: PoolDatabase) -> tuple[list[bool], dict[int, int], int, dict[int, int]]:
        seen = PostgresSeen(database)
        claims = [await seen.claim(10, 1), await seen.claim(10, 1), await seen.claim(12, 1), await seen.claim(11, 2)]
        async with database.connection() as conn:
            await conn.execute("UPDATE discord_seen SET claimed_at = now() - interval '2 days' WHERE message_id = 12")
        before = datetime.now(UTC) - timedelta(days=1)
        last = await seen.last(before)
        pruned = await seen.prune(before)
        return claims, last, pruned, await seen.last(before - timedelta(days=5))

    claims, last, pruned, after = against(db_url, scenario)
    assert claims == [True, False, True, True]
    assert last == {1: 10, 2: 11}, "the aged claim is outside the window"
    assert (pruned, after) == (1, {1: 10, 2: 11})


def test_the_discord_token_comes_from_the_environment() -> None:
    assert from_env({"DATABASE_URL": "x", "DISCORD_BOT_TOKEN": "t"}).discord_bot_token == "t"
    assert from_env({"DATABASE_URL": "x"}).discord_bot_token == ""


def test_the_discord_singleton_runs_with_no_env_token_since_the_connection_may_hold_one() -> None:
    settings = Settings(database_url="x", build_version="t", etcd_url="http://127.0.0.1:1", site="willow")
    running = singletons(settings)
    for coroutine in running:
        coroutine.close()
    assert len(running) == 11
    bare = singletons(Settings(database_url="x", build_version="t"))
    for coroutine in bare:
        coroutine.close()
    assert len(bare) == 10, "without etcd, every singleton but fail-back"
