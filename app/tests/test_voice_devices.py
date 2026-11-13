"""Satellites as devices: the CLI's `satellite` command sets a device's ESPHome host and room speaker, the schema refuses
a blank host or a speaker that is not a media player, `Devices.satellites` lists every household's unrevoked
satellites; and the settings and wiring that start the singleton."""

import asyncio

import pytest
from ashley import services
from ashley.channels.devices import Devices, DevicesUnavailable
from ashley.channels.devices.__main__ import main
from ashley.channels.model import Satellite
from ashley.channels.postgres_devices import PostgresDevices
from ashley.db.pool import PoolDatabase
from ashley.settings import Settings, from_env
from ashley.wiring_singletons import singletons
from contract.conversations_support import db_url as db_url, household
from contract.conversations_support import migrated_template as migrated_template, scalar
from voice_support import satellite_row


def satellites(url: str) -> list[Satellite]:
    found: list[list[Satellite]] = []

    async def scenario() -> None:
        database = PoolDatabase(url)
        await database.open()
        try:
            found.append(await PostgresDevices(database).satellites())
        finally:
            await database.close()

    asyncio.run(scenario())
    return found[0]


def cli(url: str, monkeypatch: pytest.MonkeyPatch, *argv: str) -> int:
    monkeypatch.setenv("DATABASE_URL", url)
    return main(list(argv))


def plain_device(url: str, household_id: int, name: str) -> int:
    return int(scalar(url, "INSERT INTO devices (household_id, name, place, audience, medium, kind, token_sha256) "
                           "VALUES (%s, %s, 'office', 'present', 'spoken', 'command', sha256(%s::bytea)) RETURNING id",
                      (household_id, name, name.encode())))


def test_the_cli_makes_a_device_a_satellite_and_changes_or_clears_its_speaker(
        db_url: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    home = household(db_url)
    echo = plain_device(db_url, home, "office echo")
    assert satellites(db_url) == [], "control: a plain device is no satellite"
    assert cli(db_url, monkeypatch, "satellite", str(echo), "--host", "10.99.3.20") == 0
    [got] = satellites(db_url)
    assert (got.device.id, got.device.household_id, got.device.place, got.host, got.room_speaker) == (
        echo, home, "office", "10.99.3.20", None)
    assert cli(db_url, monkeypatch, "satellite", str(echo), "--host", "echo.iot", "--room-speaker",
               "media_player.office") == 0
    assert [(s.host, s.room_speaker) for s in satellites(db_url)] == [("echo.iot", "media_player.office")]
    assert cli(db_url, monkeypatch, "satellite", str(echo), "--host", "echo.iot") == 0
    assert [s.room_speaker for s in satellites(db_url)] == [None]
    assert f"device {echo} is a satellite" in capsys.readouterr().out


@pytest.mark.parametrize(("argv", "status"), [
    (["--host", " "], 2),
    (["--host", "a b"], 2),
    (["--host", "h", "--room-speaker", "light.office"], 2),
    (["--host", "h", "--room-speaker", "media_player.Office"], 2),
])
def test_the_cli_refuses_a_bad_host_or_speaker(db_url: str, monkeypatch: pytest.MonkeyPatch, argv: list[str],
                                               status: int) -> None:
    echo = plain_device(db_url, household(db_url), "office echo")
    assert cli(db_url, monkeypatch, "satellite", str(echo), *argv) == status
    assert satellites(db_url) == []


def test_an_unknown_or_revoked_device_cannot_become_a_satellite(db_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    echo = plain_device(db_url, household(db_url), "office echo")
    assert cli(db_url, monkeypatch, "satellite", "999", "--host", "h") == 1
    assert cli(db_url, monkeypatch, "revoke", str(echo)) == 0
    assert cli(db_url, monkeypatch, "satellite", str(echo), "--host", "h") == 1


def test_satellites_span_households_skip_revoked_and_plain_devices_and_are_ordered(db_url: str) -> None:
    first, second = household(db_url, "one"), household(db_url, "two")
    a = satellite_row(db_url, second, "10.0.0.2", name="a")
    plain_device(db_url, first, "tablet")
    b = satellite_row(db_url, first, "10.0.0.3", "media_player.kitchen", name="b")
    gone = satellite_row(db_url, first, "10.0.0.4", name="gone")
    scalar(db_url, "UPDATE devices SET revoked_at = now() WHERE id = %s RETURNING id", (gone.device.id,))
    assert satellites(db_url) == [a, b]


def test_the_null_devices_has_no_satellites_to_give() -> None:
    services.unregister(Devices)
    with pytest.raises(DevicesUnavailable):
        asyncio.run(services.get(Devices).satellites())


def test_a_clip_base_url_and_the_key_seed_are_read_from_the_env() -> None:
    settings = from_env({"DATABASE_URL": "x", "VOICE_CLIP_BASE_URL": "https://ashley.test/", "ESPHOME_NOISE_PSK": "k"})
    assert (settings.voice_clip_base_url, settings.esphome_noise_psk) == ("https://ashley.test", "k")


@pytest.mark.parametrize(("voice", "count"), [("", 11), ("https://ashley.test", 12)])
def test_the_satellites_singleton_runs_only_with_a_clip_base_url(voice: str, count: int) -> None:
    settings = Settings(database_url="x", build_version="t", etcd_url="http://127.0.0.1:1", site="willow",
                        voice_clip_base_url=voice, esphome_noise_psk="k" if voice else "")
    running = singletons(settings)
    for coroutine in running:
        coroutine.close()
    assert len(running) == count
    bare = singletons(Settings(database_url="x", build_version="t", voice_clip_base_url=voice,
                               esphome_noise_psk="k" if voice else ""))
    for coroutine in bare:
        coroutine.close()
    assert len(bare) == count - 1, "without etcd, every singleton but fail-back"
