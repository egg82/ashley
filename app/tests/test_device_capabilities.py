"""A device's capabilities: the migration gives an existing device what the old rule gave it, registration says what a
new one can do, and only a text screen that is not a satellite, a Discord server or the house can take controls."""

import asyncio
import re
import secrets

import psycopg
import pytest
from alembic import command
from ashley.channels.model import Capability
from ashley.channels.postgres_devices import PostgresDevices
from ashley.db.migrate import alembic_config
from ashley.db.pool import PoolDatabase
from contract.conversations_support import db_url as db_url, household, migrated_template as migrated_template
from contract.conversations_support import scalar
from test_devices import add
from test_proposals_migration import revision_named


def insert(url: str, home: int, name: str, medium: str, extra: str = "", values: str = "") -> int:
    return int(scalar(url, f"INSERT INTO devices (household_id, name, place, audience, medium, kind, token_sha256{extra}) "
                           f"VALUES (%s, %s, 'hall', 'present', %s, 'chat', sha256(%s::bytea){values}) RETURNING id",
                      (home, name, medium, secrets.token_bytes(8))))


def capabilities_of(url: str, device_id: int) -> list[str]:
    return list(scalar(url, "SELECT capabilities FROM devices WHERE id = %s", (device_id,)))


def listed(url: str, home: int) -> dict[int, frozenset[Capability]]:
    async def scenario() -> dict[int, frozenset[Capability]]:
        db = PoolDatabase(url)
        await db.open()
        try:
            return {item.device.id: item.capabilities for item in await PostgresDevices(db).of_household(home)}
        finally:
            await db.close()
    return asyncio.run(scenario())


def test_the_migration_gives_a_device_what_the_old_rule_gave_it(empty_database: str) -> None:
    this, before = revision_named("device_capabilities")
    command.upgrade(alembic_config(empty_database), before)
    home = int(scalar(empty_database, "INSERT INTO households (name) VALUES ('h') RETURNING id"))
    rows = {
        "tablet": insert(empty_database, home, "tablet", "text"),
        "speaker": insert(empty_database, home, "speaker", "spoken"),
        "texting satellite": insert(empty_database, home, "t1", "text", ", esphome_host", ", 'sat.local'"),
        "text server": insert(empty_database, home, "t2", "text", ", discord_guild_id, discord_home_channel_id", ", 9, 7"),
        "text house": insert(empty_database, home, "t3", "text", ", house", ", true"),
    }
    command.upgrade(alembic_config(empty_database), this)
    assert {name: capabilities_of(empty_database, i) for name, i in rows.items()} == {
        "tablet": ["controls"], "speaker": [], "texting satellite": [], "text server": [], "text house": []}


def test_downgrading_drops_the_column(empty_database: str) -> None:
    this, before = revision_named("device_capabilities")
    command.upgrade(alembic_config(empty_database), this)
    command.downgrade(alembic_config(empty_database), before)
    with psycopg.connect(empty_database) as conn:
        assert conn.execute("SELECT count(*) FROM information_schema.columns WHERE table_name = 'devices' "
                            "AND column_name = 'capabilities'").fetchone() == (0,)


def register(url: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: int, name: str,
             medium: str, *flags: str) -> tuple[int, int | None]:
    status, out = add(url, monkeypatch, capsys, "add", str(home), name, "--place", "hall", "--audience", "present",
                      "--medium", medium, "--kind", "chat", *flags)
    found = re.search(r"^device (\d+)$", out, re.MULTILINE)
    return status, int(found[1]) if found else None


def test_registration_says_what_a_device_can_do(db_url: str, monkeypatch: pytest.MonkeyPatch,
                                                capsys: pytest.CaptureFixture[str]) -> None:
    home = household(db_url)
    _, tablet = register(db_url, monkeypatch, capsys, home, "tablet", "text", "--controls")
    _, plain = register(db_url, monkeypatch, capsys, home, "plain", "text")
    _, speaker = register(db_url, monkeypatch, capsys, home, "speaker", "spoken")
    assert tablet and plain and speaker
    assert listed(db_url, home) == {tablet: {"controls"}, plain: frozenset(), speaker: frozenset()}


def test_a_spoken_device_cannot_be_registered_with_controls(db_url: str, monkeypatch: pytest.MonkeyPatch,
                                                            capsys: pytest.CaptureFixture[str]) -> None:
    home = household(db_url)
    assert register(db_url, monkeypatch, capsys, home, "speaker", "spoken", "--controls") == (2, None)
    assert listed(db_url, home) == {}


def test_a_person_can_say_a_device_takes_controls_and_take_it_back(db_url: str, monkeypatch: pytest.MonkeyPatch,
                                                                   capsys: pytest.CaptureFixture[str]) -> None:
    home = household(db_url)
    _, plain = register(db_url, monkeypatch, capsys, home, "plain", "text")
    assert plain
    assert add(db_url, monkeypatch, capsys, "controls", str(plain))[0] == 0
    assert listed(db_url, home)[plain] == {"controls"}
    assert add(db_url, monkeypatch, capsys, "controls", str(plain), "--off")[0] == 0
    assert listed(db_url, home)[plain] == frozenset()
    assert add(db_url, monkeypatch, capsys, "controls", "999999")[0] == 1


def test_a_device_that_takes_controls_cannot_become_a_satellite_a_server_or_the_house(
        db_url: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    home = household(db_url)
    _, tablet = register(db_url, monkeypatch, capsys, home, "tablet", "text", "--controls")
    spoken = insert(db_url, home, "speaker", "spoken")
    assert tablet
    d = str(tablet)
    assert add(db_url, monkeypatch, capsys, "satellite", d, "--host", "sat.local")[0] == 2
    assert add(db_url, monkeypatch, capsys, "discord", d, "5", "6")[0] == 2
    assert add(db_url, monkeypatch, capsys, "house", d)[0] == 2
    assert add(db_url, monkeypatch, capsys, "controls", str(spoken))[0] == 2
    assert capabilities_of(db_url, tablet) == ["controls"] and capabilities_of(db_url, spoken) == []
    assert add(db_url, monkeypatch, capsys, "controls", d, "--off")[0] == 0
    assert add(db_url, monkeypatch, capsys, "house", d)[0] == 0
