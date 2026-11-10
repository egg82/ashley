"""A household's device list, read from Postgres and served at `GET /api/devices`: a device of another household or a
revoked one is never listed, its form comes from what it is wired to rather than its name, and nothing that signs a
device in or reaches it is read or served."""

import asyncio
import hashlib
import secrets
from collections.abc import Generator

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo
from ashley import services
from ashley.api.models import DevicesResponse, ErrorResponse, ListedDevice
from ashley.api.person import SESSION_COOKIE
from ashley.channels.devices import Devices, DevicesUnavailable, NullDevices
from ashley.channels.model import Listed
from ashley.channels.postgres_devices import PostgresDevices
from ashley.db.pool import PoolDatabase
from ashley.main import create_app
from ashley.people import admin
from ashley.settings import Settings
from contract.conversations_support import db_url as db_url, household, migrated_template as migrated_template
from contract.conversations_support import scalar
from fastapi.testclient import TestClient

PUBLIC = "https://ashley.test"
READABLE = ("id", "household_id", "name", "place", "audience", "medium", "kind", "remembers", "revoked_at",
            "esphome_host", "discord_guild_id", "house")


def device(url: str, household_id: int, name: str, extra: str = "", values: str = "") -> int:
    return int(scalar(url, f"INSERT INTO devices (household_id, name, place, audience, medium, kind, token_sha256{extra}) "
                           f"VALUES (%s, %s, 'kitchen', 'present', 'spoken', 'command', sha256(%s::bytea){values}) "
                           "RETURNING id", (household_id, name, secrets.token_bytes(8))))


def satellite(url: str, household_id: int, name: str) -> int:
    return device(url, household_id, name, ", esphome_host", ", 'sat.local'")


def discord(url: str, household_id: int, name: str, guild: int) -> int:
    return device(url, household_id, name, ", discord_guild_id, discord_home_channel_id", f", {guild}, 7")


def listed(url: str, household_id: int) -> list[Listed]:
    async def scenario() -> list[Listed]:
        database = PoolDatabase(url)
        await database.open()
        try:
            return await PostgresDevices(database).of_household(household_id)
        finally:
            await database.close()

    return asyncio.run(scenario())


def test_a_household_lists_only_its_own_unrevoked_devices_by_what_they_are_wired_to(db_url: str) -> None:
    home, other = household(db_url), household(db_url, "other")
    # Names say the opposite of what the wiring says.
    sat = satellite(db_url, home, "discord")
    server = discord(db_url, home, "satellite", 11)
    plain = device(db_url, home, "satellite")
    gone = device(db_url, home, "gone")
    scalar(db_url, "UPDATE devices SET revoked_at = now() WHERE id = %s RETURNING id", (gone,))
    satellite(db_url, other, "theirs")
    found = listed(db_url, home)
    assert [(item.device.id, item.form) for item in found] == [(sat, "satellite"), (server, "discord_server"),
                                                              (plain, "other")]
    assert {item.device.household_id for item in found} == {home}
    assert all(not hasattr(item, "host") and not hasattr(item.device, "token_sha256") for item in found)
    assert listed(db_url, other)[0].device.name == "theirs"


def test_a_household_with_no_devices_lists_none(db_url: str) -> None:
    assert listed(db_url, household(db_url)) == []


def test_the_read_does_not_touch_the_token_column(db_url: str) -> None:
    home = household(db_url)
    satellite(db_url, home, "kitchen")
    role = "reader_" + secrets.token_hex(4)
    with psycopg.connect(db_url, autocommit=True) as conn:
        who = sql.Identifier(role)
        conn.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD 'r'").format(who))
        conn.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(who))
        conn.execute(sql.SQL("GRANT SELECT ({}) ON devices TO {}").format(
            sql.SQL(", ").join(sql.Identifier(c) for c in READABLE), who))
        try:
            assert [item.form for item in listed(make_conninfo(db_url, user=role, password="r"), home)] == ["satellite"]
        finally:
            conn.execute(sql.SQL("DROP OWNED BY {}").format(who))
            conn.execute(sql.SQL("DROP ROLE {}").format(who))


def test_an_unwired_service_is_unavailable() -> None:
    with pytest.raises(DevicesUnavailable):
        asyncio.run(NullDevices().of_household(1))


@pytest.fixture
def client(db_url: str) -> Generator[tuple[TestClient, int]]:
    with psycopg.connect(db_url) as conn:
        hid = admin.add_household(conn, "home", "America/Denver")
        pid = admin.add_person(conn, hid, "Alana")
        account = admin.add_account(conn, pid, "oidc", "sub-alana")
        token = secrets.token_urlsafe(16)
        conn.execute("INSERT INTO sessions (token_sha256, account_id, household_id, expires_at) "
                     "VALUES (%s, %s, %s, now() + interval '1 day')",
                     (hashlib.sha256(token.encode()).digest(), account, hid))
    app = create_app(Settings(database_url=db_url, build_version="t", public_url=PUBLIC))
    with TestClient(app, base_url=PUBLIC, follow_redirects=False) as c:
        c.cookies.set(SESSION_COOKIE, token, domain="ashley.test")
        yield c, hid


def test_the_route_serves_the_households_devices_and_nothing_that_reaches_them(
        client: tuple[TestClient, int], db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    c, home = client
    sat = satellite(db_url, home, "kitchen")
    satellite(db_url, household(db_url, "other"), "theirs")
    with caplog.at_level("INFO", logger="ashley.api"):
        got = c.get("/api/devices")
    assert got.status_code == 200
    assert got.json() == {"devices": [{"id": sat, "name": "kitchen", "place": "kitchen", "form": "satellite",
                                       "audience": "present", "medium": "spoken"}]}
    assert DevicesResponse.model_validate(got.json()).devices == [
        ListedDevice(id=sat, name="kitchen", place="kitchen", form="satellite", audience="present", medium="spoken")]
    assert "sat.local" not in got.text and "sat.local" not in caplog.text
    assert any(r.getMessage() == "devices.listed" and getattr(r, "fields") == {"household": home, "count": 1}
               for r in caplog.records)


def test_an_empty_household_is_an_empty_list(client: tuple[TestClient, int]) -> None:
    assert client[0].get("/api/devices").json() == {"devices": []}


def test_without_a_session_it_is_401(client: tuple[TestClient, int]) -> None:
    c, _ = client
    c.cookies.clear()
    got = c.get("/api/devices")
    assert got.status_code == 401
    assert ErrorResponse.model_validate(got.json()).code == "unauthorized"


def test_when_devices_is_not_wired_it_is_503(client: tuple[TestClient, int]) -> None:
    c, _ = client
    services.register(Devices, NullDevices())
    got = c.get("/api/devices")
    assert got.status_code == 503
    assert ErrorResponse.model_validate(got.json()).code == "unavailable"
