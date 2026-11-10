"""`POST /api/wakes`: a device's bearer token, 202 `WakeAccepted`, one wake per event id however it arrives, refusals that
store nothing, validation failures that echo nothing, the device's rate, and no wake text in a log."""

from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import pytest
from ashley import logs, services
from ashley.api.wake_models import WakeAccepted
from ashley.channels.devices import Devices
from ashley.channels.model import Device, DiscordServer, Listed, Satellite
from ashley.main import create_app
from ashley.senses.wakes import Wakes, WakesUnavailable
from ashley.settings import Settings
from contract.conversations_support import household, scalar
from fastapi.testclient import TestClient
from wb_support import MemoryWakes, add_device, count

TOKEN = "wb-token-7d41f0a2"
HA = Device(7, 10, "ha", "house", "present", "text", "chat")
OTHER = Device(8, 11, "other ha", "house", "present", "text", "chat")
OTHER_TOKEN = "wb-token-other-93ac"
SAT_TOKEN, KIOSK_TOKEN, DISCORD_TOKEN = "wb-token-sat-1", "wb-token-kiosk-2", "wb-token-discord-3"
SAT = Device(9, 10, "kitchen", "kitchen", "present", "spoken", "command")
KIOSK = Device(12, 10, "tablet", "hallway", "household", "text", "chat")
SERVER = DiscordServer(Device(13, 10, "server", "discord", "household", "text", "chat"), 900, 901)


@dataclass
class FakeDevices(Devices):
    over: bool = False
    down: bool = False
    counted: list[int] = field(default_factory=list[int])

    async def by_token(self, token: str) -> Device | None:
        if self.down:
            from ashley.channels.devices import DevicesUnavailable
            raise DevicesUnavailable("down")
        return {TOKEN: HA, OTHER_TOKEN: OTHER, SAT_TOKEN: SAT, KIOSK_TOKEN: KIOSK,
                DISCORD_TOKEN: SERVER.device}.get(token)

    async def allow(self, device_id: int) -> bool:
        self.counted.append(device_id)
        return not self.over

    async def satellites(self) -> list[Satellite]:
        return [Satellite(SAT, "10.0.0.9", None)]

    async def discord_servers(self) -> list[DiscordServer]:
        return [SERVER]

    async def of_household(self, household_id: int) -> list[Listed]:
        every = [Listed(HA, "house"), Listed(SAT, "satellite"), Listed(KIOSK, "other"), Listed(SERVER.device, "discord_server")]
        return [x for x in every if x.device.household_id == household_id] + (
            [Listed(OTHER, "house")] if household_id == OTHER.household_id else [])


@dataclass
class Rig:
    client: TestClient
    wakes: MemoryWakes
    devices: FakeDevices


@pytest.fixture
def rig() -> Generator[Rig]:
    app = create_app(Settings(database_url="", build_version="test"))
    made = Rig(TestClient(app), MemoryWakes(), FakeDevices())
    services.register(Devices, made.devices)
    services.register(Wakes, made.wakes)
    yield made


def bearer(token: str = TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


BODY = {"event_id": "ctx-1", "event": "arrived", "who": "person.alana", "what": "front_door",
        "when": "2026-10-31T12:00:00+00:00"}


def test_a_signed_in_device_gets_202_and_its_wake_is_stored_under_its_household(rig: Rig) -> None:
    got = rig.client.post("/api/wakes", json=BODY, headers=bearer())
    assert got.status_code == 202
    accepted = WakeAccepted.model_validate(got.json())
    assert accepted.duplicate is False
    ((id_, stored),) = rig.wakes.stored.values()
    assert id_ == accepted.id
    assert (stored.household_id, stored.event_id, stored.event, stored.who, stored.what) == (
        10, "ctx-1", "arrived", "person.alana", "front_door")
    assert stored.at.isoformat() == "2026-10-31T12:00:00+00:00"
    assert rig.wakes.handed_in_by == [7]


def test_only_event_id_and_event_are_required(rig: Rig) -> None:
    got = rig.client.post("/api/wakes", json={"event_id": "x", "event": "arrived"}, headers=bearer())
    assert got.status_code == 202
    ((_, stored),) = rig.wakes.stored.values()
    assert (stored.who, stored.what) == (None, None)
    assert stored.at.tzinfo is not None


def test_the_same_event_id_twice_is_one_wake_and_the_second_says_duplicate(rig: Rig) -> None:
    first = rig.client.post("/api/wakes", json=BODY, headers=bearer())
    second = rig.client.post("/api/wakes", json={**BODY, "event": "left"}, headers=bearer())
    assert (first.status_code, second.status_code) == (202, 202)
    a, b = WakeAccepted.model_validate(first.json()), WakeAccepted.model_validate(second.json())
    assert (a.duplicate, b.duplicate, a.id) == (False, True, b.id)
    assert len(rig.wakes.stored) == 1


def test_the_same_event_id_from_another_household_is_its_own_wake(rig: Rig) -> None:
    a = rig.client.post("/api/wakes", json=BODY, headers=bearer())
    b = rig.client.post("/api/wakes", json=BODY, headers=bearer(OTHER_TOKEN))
    assert WakeAccepted.model_validate(b.json()).duplicate is False and a.json()["id"] != b.json()["id"]
    assert len(rig.wakes.stored) == 2


UNAUTHORIZED: list[dict[str, str]] = [
    {}, {"Authorization": ""}, {"Authorization": "Bearer"}, {"Authorization": "Bearer "},
    {"Authorization": f"Basic {TOKEN}"}, {"Authorization": TOKEN}, {"Authorization": "Bearer nope"},
    {"Authorization": f"Bearer {TOKEN}x"}, {"X-Token": TOKEN}]


@pytest.mark.parametrize("headers", UNAUTHORIZED)
def test_without_a_good_device_token_the_wake_is_refused_and_nothing_is_stored(rig: Rig, headers: dict[str, str]) -> None:
    got = rig.client.post("/api/wakes", json=BODY, headers=headers)
    assert got.status_code in (401, 403)
    assert rig.wakes.stored == {}
    assert rig.devices.counted == []


def test_a_token_is_checked_before_the_body(rig: Rig) -> None:
    got = rig.client.post("/api/wakes", json={"nonsense": 1}, headers={})
    assert got.status_code in (401, 403)


def test_the_devices_rate_refuses_the_wake_and_stores_nothing(rig: Rig) -> None:
    rig.devices.over = True
    got = rig.client.post("/api/wakes", json=BODY, headers=bearer())
    assert got.status_code == 429
    assert rig.wakes.stored == {}
    assert rig.devices.counted == [7]


def test_a_request_inside_the_rate_is_counted_against_the_device(rig: Rig) -> None:
    rig.client.post("/api/wakes", json=BODY, headers=bearer())
    assert rig.devices.counted == [7]


PLANTED = "PLANTED-zq-8841"
INVALID: dict[str, dict[str, object]] = {
    "event_id with space": {"event_id": f"{PLANTED} x", "event": "arrived"},
    "empty event_id": {"event_id": "", "event": "arrived"},
    "long event_id": {"event_id": PLANTED + "a" * 200, "event": "arrived"},
    "event not a slug": {"event_id": "e", "event": f"Arrived {PLANTED}"},
    "who not a person": {"event_id": "e", "event": "arrived", "who": f"light.{PLANTED}"},
    "what not a slug": {"event_id": "e", "event": "arrived", "what": f"Free text {PLANTED}"},
    "when not a time": {"event_id": "e", "event": "arrived", "when": PLANTED},
    "extra field": {"event_id": "e", "event": "arrived", "message": PLANTED},
    "event_id missing": {"event": "arrived", "who": f"person.{PLANTED}"},
}


@pytest.mark.parametrize("name", INVALID)
def test_an_invalid_wake_is_422_stores_nothing_and_echoes_nothing(rig: Rig, name: str) -> None:
    got = rig.client.post("/api/wakes", json=INVALID[name], headers=bearer())
    assert got.status_code == 422
    assert PLANTED not in got.text
    assert rig.wakes.stored == {}


def test_a_body_that_is_not_json_is_refused_without_echo(rig: Rig) -> None:
    got = rig.client.post("/api/wakes", content=f"{PLANTED} not json", headers={**bearer(), "Content-Type": "application/json"})
    assert got.status_code == 422 and PLANTED not in got.text and rig.wakes.stored == {}


def test_wakes_that_cannot_be_stored_answer_unavailable_and_say_nothing_of_the_wake(rig: Rig) -> None:
    rig.wakes.error = WakesUnavailable("down")
    got = rig.client.post("/api/wakes", json=BODY, headers=bearer())
    assert got.status_code == 503
    assert "front_door" not in got.text and "person.alana" not in got.text


def test_the_wakes_route_is_unwired_by_default_so_a_wake_is_never_taken_in_and_dropped(rig: Rig) -> None:
    services.unregister(Wakes)
    got = rig.client.post("/api/wakes", json=BODY, headers=bearer())
    assert got.status_code == 503


def test_only_post_is_served(rig: Rig) -> None:
    assert rig.client.get("/api/wakes", headers=bearer()).status_code in (404, 405)


def test_nothing_of_a_wake_reaches_a_log_line(rig: Rig, capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup({"LOG_LEVEL": "debug"})
    body = {"event_id": "PLANTED-EVID-zq", "event": "planted_evt", "who": "person.plantedwho", "what": "plantedwhat"}
    rig.client.post("/api/wakes", json=body, headers=bearer())
    rig.client.post("/api/wakes", json=body, headers=bearer())
    rig.client.post("/api/wakes", json={**body, "who": f"x {PLANTED}"}, headers=bearer())
    out = capsys.readouterr().out
    assert "ts=" in out
    for planted in ("PLANTED-EVID-zq", "planted_evt", "plantedwho", "plantedwhat", PLANTED, TOKEN):
        assert planted not in out


def test_on_a_real_database_many_posts_of_one_event_are_one_wake(db_url: str) -> None:
    home = household(db_url)
    add_device(db_url, home, TOKEN, house=True)
    app = create_app(Settings(database_url=db_url, build_version="test"))
    with TestClient(app) as client:
        def post(_: int) -> dict[str, object]:
            return client.post("/api/wakes", json=BODY, headers=bearer()).json()
        with ThreadPoolExecutor(8) as pool:
            got = list(pool.map(post, range(8)))
    assert len({g["id"] for g in got}) == 1
    assert sorted(bool(g["duplicate"]) for g in got) == [False] + [True] * 7
    assert count(db_url, "SELECT count(*) FROM wakes") == 1


def test_on_a_real_database_a_revoked_or_unknown_token_is_refused(db_url: str) -> None:
    home = household(db_url)
    add_device(db_url, home, TOKEN, house=True)
    app = create_app(Settings(database_url=db_url, build_version="test"))
    with TestClient(app) as client:
        assert client.post("/api/wakes", json=BODY, headers=bearer("wb-token-wrong")).status_code in (401, 403)
        assert client.post("/api/wakes", json=BODY, headers=bearer()).status_code == 202
    assert count(db_url, "SELECT count(*) FROM wakes") == 1
    assert scalar(db_url, "SELECT household_id FROM wakes") == home


@pytest.mark.parametrize("token", [SAT_TOKEN, DISCORD_TOKEN, KIOSK_TOKEN])
def test_only_the_houses_device_may_wake_her(rig: Rig, token: str) -> None:
    got = rig.client.post("/api/wakes", json=BODY, headers=bearer(token))
    assert got.status_code == 403
    assert got.json()["code"] == "forbidden"
    assert rig.wakes.stored == {}


def test_a_refused_device_is_not_counted_as_a_wake_handed_in(rig: Rig) -> None:
    rig.client.post("/api/wakes", json=BODY, headers=bearer(KIOSK_TOKEN))
    assert rig.wakes.handed_in_by == []


def test_the_houses_device_may(rig: Rig) -> None:
    assert rig.client.post("/api/wakes", json=BODY, headers=bearer()).status_code == 202


def test_on_a_real_database_a_device_not_marked_house_is_refused_until_it_is(db_url: str) -> None:
    from ashley.channels.postgres_devices import PostgresDevices
    from ashley.db.pool import PoolDatabase
    from contract.conversations_support import run

    home = household(db_url)
    device = add_device(db_url, home, TOKEN)
    app = create_app(Settings(database_url=db_url, build_version="test"))

    marked: list[bool] = []

    async def mark() -> None:
        db = PoolDatabase(db_url, connect_timeout_s=5.0)
        await db.open()
        try:
            marked.append(await PostgresDevices(db).set_house(device))
        finally:
            await db.close()

    with TestClient(app) as client:
        assert client.post("/api/wakes", json=BODY, headers=bearer()).status_code == 403
        assert count(db_url, "SELECT count(*) FROM wakes") == 0
        run(mark())
        assert marked == [True]
        assert client.post("/api/wakes", json=BODY, headers=bearer()).status_code == 202
    assert count(db_url, "SELECT count(*) FROM wakes") == 1


def test_on_a_real_database_a_satellite_token_is_refused(db_url: str) -> None:
    from ashley.channels.postgres_devices import PostgresDevices
    from ashley.channels.device_rate import load
    from ashley.db.pool import PoolDatabase
    from contract.conversations_support import run

    home = household(db_url)
    device = add_device(db_url, home, TOKEN)

    async def make_satellite() -> None:
        db = PoolDatabase(db_url, connect_timeout_s=5.0)
        await db.open()
        try:
            assert await PostgresDevices(db, load()).set_satellite(device, "10.0.0.9", None)
        finally:
            await db.close()

    run(make_satellite())
    app = create_app(Settings(database_url=db_url, build_version="test"))
    with TestClient(app) as client:
        assert client.post("/api/wakes", json=BODY, headers=bearer()).status_code == 403
    assert count(db_url, "SELECT count(*) FROM wakes") == 0
