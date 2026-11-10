"""PostgresDevices and its CLI against a real database: a token signs in by its SHA-256, revoked and unknown tokens
sign in none, and the token is printed once and never logged."""

import hashlib
import re

import pytest
from ashley import services, wiring
from ashley.channels.devices import Devices, DevicesUnavailable
from ashley.channels.devices.__main__ import main
from ashley.channels.model import Device
from ashley.channels.postgres_devices import PostgresDevices
from ashley.conversations.conversations import Conversations
from ashley.db.database import Database
from ashley.db.pool import PoolDatabase
from ashley.inference.inference import Inference
from ashley.settings import Settings
from contract.conversations_support import db_url as db_url, household, migrated_template as migrated_template, run
from contract.conversations_support import scalar


def by_token(url: str, token: str) -> Device | None:
    found: list[Device | None] = []

    async def scenario() -> None:
        db = PoolDatabase(url)
        await db.open()
        try:
            found.append(await PostgresDevices(db).by_token(token))
        finally:
            await db.close()

    run(scenario())
    return found[0]


def add(url: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str]:
    monkeypatch.setenv("DATABASE_URL", url)
    status = main(list(argv))
    return status, capsys.readouterr().out


def test_an_added_device_signs_in_by_its_token_until_revoked(db_url: str, monkeypatch: pytest.MonkeyPatch,
                                                            capsys: pytest.CaptureFixture[str]) -> None:
    home = household(db_url)
    status, out = add(db_url, monkeypatch, capsys, "add", str(home), "tablet", "--place", "hallway", "--audience",
                      "present", "--medium", "text", "--kind", "chat")
    assert status == 0
    found = re.search(r"^device (\d+)\ntoken (\S+)$", out, re.MULTILINE)
    assert found is not None
    device_id, token = int(found[1]), found[2]
    assert by_token(db_url, token) == Device(device_id, home, "tablet", "hallway", "present", "text", "chat")
    stored = scalar(db_url, "SELECT token_sha256 FROM devices WHERE id = %s", (device_id,))
    assert bytes(stored) == hashlib.sha256(token.encode()).digest()
    assert by_token(db_url, token[:-1]) is None and by_token(db_url, "") is None

    status, out = add(db_url, monkeypatch, capsys, "revoke", str(device_id))
    assert status == 0 and token not in out
    assert by_token(db_url, token) is None
    assert add(db_url, monkeypatch, capsys, "revoke", str(device_id))[0] == 1


def test_the_token_and_its_hash_are_never_logged(db_url: str, monkeypatch: pytest.MonkeyPatch,
                                                 capsys: pytest.CaptureFixture[str]) -> None:
    home = household(db_url)
    _, out = add(db_url, monkeypatch, capsys, "add", str(home), "kitchen", "--place", "kitchen", "--audience",
                 "household", "--medium", "spoken", "--kind", "command")
    token = out.split("token ", 1)[1].strip()
    log_lines = [line for line in out.splitlines() if line.startswith("ts=")]
    assert any("devices.added" in line for line in log_lines)
    digest = hashlib.sha256(token.encode()).hexdigest()
    assert not [line for line in log_lines if token in line or digest in line]


def test_an_unknown_household_writes_nothing(db_url: str, monkeypatch: pytest.MonkeyPatch,
                                             capsys: pytest.CaptureFixture[str]) -> None:
    status, _ = add(db_url, monkeypatch, capsys, "add", "999", "x", "--place", "p", "--audience", "present",
                    "--medium", "text", "--kind", "chat")
    assert status == 1
    assert scalar(db_url, "SELECT count(*) FROM devices") == 0


def test_a_bad_command_is_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://nowhere.invalid/x")
    with pytest.raises(SystemExit) as raised:
        main(["add", "1", "x", "--place", "p", "--audience", "owner", "--medium", "text", "--kind", "chat"])
    assert raised.value.code == 2
    assert main(["add", "1", " ", "--place", "p", "--audience", "present", "--medium", "text", "--kind", "chat"]) == 2


def test_an_unreachable_database_is_unavailable() -> None:
    async def scenario() -> None:
        db = PoolDatabase("postgresql://127.0.0.1:1/x", connect_timeout_s=0.2)
        await db.open()
        try:
            with pytest.raises(DevicesUnavailable):
                await PostgresDevices(db).by_token("anything")
        finally:
            await db.close()

    run(scenario())


def test_the_app_wires_postgres_devices() -> None:
    wiring.wire(Settings(database_url="postgresql://nowhere.invalid/x", build_version="x"))
    try:
        assert isinstance(services.get(Devices), PostgresDevices)
    finally:
        for interface in (Devices, Conversations, Inference, Database):
            services.unregister(interface)
