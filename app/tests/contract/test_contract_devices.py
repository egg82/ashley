"""Devices over a real database: a token signs in the device whose stored SHA-256 it matches; an unknown, revoked or
empty token, or the stored hash itself, signs in none; the Null Object and an unreachable database raise
DevicesUnavailable; neither the token nor its hash reaches a log line or an exception message."""

import hashlib
import subprocess
import sys

import pytest
from ashley import logs, services
from ashley.channels.devices import Devices, DevicesUnavailable
from ashley.channels.model import Device
from contract_support import unreachable_conninfo
from conversations_support import run
from people_support import device, devices, execute, home

TOKEN = "zqTOKEN-4b1d9c7e8f2a"


def test_a_token_signs_in_its_device_with_every_field(db_url: str) -> None:
    house = home(db_url)
    other = device(db_url, house, "another token", "hallway tablet", "hallway", "household", "text", "chat")
    mine = device(db_url, house, TOKEN, "kitchen satellite", "kitchen", "present", "spoken", "command")

    async def scenario() -> None:
        async with devices(db_url) as d:
            assert await d.by_token(TOKEN) == Device(mine, house, "kitchen satellite", "kitchen", "present", "spoken",
                                                     "command")
            assert await d.by_token("another token") == Device(other, house, "hallway tablet", "hallway",
                                                               "household", "text", "chat")

    run(scenario())


@pytest.mark.parametrize("token", [
    "", "unknown", TOKEN.upper(), TOKEN[:-1], f"{TOKEN} ", f" {TOKEN}",
    hashlib.sha256(TOKEN.encode()).hexdigest(),          # what a database read yields is not a token
])
def test_a_token_that_signs_in_nothing_is_none(db_url: str, token: str) -> None:
    device(db_url, home(db_url), TOKEN)

    async def scenario() -> None:
        async with devices(db_url) as d:
            assert await d.by_token(TOKEN) is not None, "control: the real token signs in"
            assert await d.by_token(token) is None

    run(scenario())


def test_a_revoked_device_signs_in_nothing(db_url: str) -> None:
    house = home(db_url)
    revoked = device(db_url, house, TOKEN)
    kept = device(db_url, house, "kept")
    execute(db_url, "UPDATE devices SET revoked_at = now() WHERE id = %s", (revoked,))

    async def scenario() -> None:
        async with devices(db_url) as d:
            assert await d.by_token(TOKEN) is None
            got = await d.by_token("kept")
            assert got is not None and got.id == kept

    run(scenario())


def test_an_unreachable_database_raises_unavailable_without_the_token() -> None:
    async def scenario() -> None:
        async with devices(unreachable_conninfo(), connect_timeout_s=0.1) as d:
            with pytest.raises(DevicesUnavailable) as caught:
                await d.by_token(TOKEN)
        assert TOKEN not in str(caught.value)

    run(scenario())


def test_the_null_object_raises_unavailable() -> None:
    services.unregister(Devices)

    async def scenario() -> None:
        with pytest.raises(DevicesUnavailable):
            await services.get(Devices).by_token(TOKEN)

    run(scenario())


def test_neither_the_token_nor_its_hash_reaches_a_log_line(db_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    device(db_url, home(db_url), TOKEN)
    logs.setup()
    capsys.readouterr()
    digest = hashlib.sha256(TOKEN.encode())

    async def scenario() -> None:
        async with devices(db_url) as d:
            assert await d.by_token(TOKEN) is not None
            assert await d.by_token(f"{TOKEN}-wrong") is None
        async with devices(unreachable_conninfo(), connect_timeout_s=0.1) as d:
            with pytest.raises(DevicesUnavailable):
                await d.by_token(TOKEN)

    run(scenario())
    out = capsys.readouterr().out
    for leaked in (TOKEN, "zqTOKEN", digest.hexdigest(), digest.hexdigest()[:12]):
        assert leaked not in out


def test_the_cli_offers_the_add_command() -> None:
    """`python -m ashley.channels.devices add` issues a token; its arguments are not in the contract, so only that
    the command is offered is checked here."""
    got = subprocess.run([sys.executable, "-m", "ashley.channels.devices", "--help"], capture_output=True, text=True,
                         timeout=60)
    assert got.returncode == 0, got.stderr[-500:]
    assert "add" in got.stdout


def test_the_people_cli_lists_its_commands() -> None:
    got = subprocess.run([sys.executable, "-m", "ashley.people", "--help"], capture_output=True, text=True,
                         timeout=60)
    assert got.returncode == 0, got.stderr[-500:]
    assert got.stdout.strip()
