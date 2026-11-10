"""POST /api/wakes through the real app: Home Assistant, signed in as a device of the household, hands in a wake of
structured fields only and gets 202 at once; the same event id again is 202 `duplicate` and stores nothing; free text
in any field, an unknown field, a missing or wrong token, a public request and a device over its rate store nothing;
and the logs carry ids and counts, never a field of the wake."""

from collections.abc import Generator
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest
from ashley import logs, services
from ashley.api.models import ErrorResponse
from ashley.api.wake_models import WakeAccepted
from ashley.channels.devices import Devices
from ashley.channels.model import Device, DiscordServer, Form, Listed, Satellite
from ashley.main import create_app
from ashley.senses.wakes import Delivery, Received, Reminder, Wake, Wakes, WakesUnavailable
from ashley.settings import Settings
from contract.conversations_support import events
from fastapi.testclient import TestClient

TOKEN = "zqHOUSE-0193"
HOUSE = Device(9, 10, "home assistant", "house", "household", "text", "chat")
OTHERS: dict[str, tuple[Device, Form]] = {
    "zqSAT": (Device(11, 10, "kitchen", "kitchen", "present", "spoken", "command"), "satellite"),
    "zqDISCORD": (Device(12, 10, "server", "discord", "household", "text", "chat"), "discord_server"),
    "zqKIOSK": (Device(13, 10, "tablet", "hallway", "present", "spoken", "chat"), "other")}
BODY = {"event_id": "01JBX3K7", "event": "alana_arrived", "who": "person.alana", "what": "front_door",
        "when": "2026-10-31T18:02:00-06:00"}


@dataclass
class FakeDevices(Devices):
    over: bool = False

    async def by_token(self, token: str) -> Device | None:
        return HOUSE if token == TOKEN else OTHERS[token][0] if token in OTHERS else None

    async def allow(self, device_id: int) -> bool:
        return not self.over

    async def satellites(self) -> list[Satellite]:
        return []

    async def discord_servers(self) -> list[DiscordServer]:
        return []

    async def of_household(self, household_id: int) -> list[Listed]:
        return [Listed(HOUSE, "house"), *(Listed(d, form) for d, form in OTHERS.values())]


@dataclass
class FakeWakes(Wakes):
    down: bool = False
    got: list[tuple[int, Wake]] = field(default_factory=list[tuple[int, Wake]])

    async def receive(self, device_id: int, wake: Wake) -> Received:
        if self.down:
            raise WakesUnavailable("down")
        for n, (_, seen) in enumerate(self.got):
            if (seen.household_id, seen.event_id) == (wake.household_id, wake.event_id):
                return Received(n + 1, False)
        self.got.append((device_id, wake))
        return Received(len(self.got), True)

    async def due(self, limit: int) -> tuple[()]:
        return ()

    async def settle(self, wake_id: int, outcome: str, next_due: datetime | None = None) -> bool:
        return False

    async def prune(self, older_than_s: float) -> int:
        return 0

    async def schedule(self, reminder: Reminder) -> int:
        raise AssertionError("the intake never schedules")

    async def reminders(self, household_id: int, person_id: int) -> tuple[()]:
        return ()

    async def cancel(self, household_id: int, person_id: int, wake_id: int) -> bool:
        return False

    async def edit(self, household_id: int, person_id: int, wake_id: int, changed: Reminder) -> bool:
        return False

    async def refire(self, wake_id: int, after_s: float) -> int:
        return 0

    async def undelivered(self, limit: int, retry_s: float, within_s: float) -> tuple[Delivery, ...]:
        return ()

    async def claim(self, wake_id: int, retry_s: float) -> bool:
        return False

    async def delivered(self, wake_id: int, reached: bool) -> None:
        return None

    async def dismiss(self, household_id: int, person_id: int, wake_id: int) -> bool:
        return False


@pytest.fixture
def wakes() -> FakeWakes:
    return FakeWakes()


@pytest.fixture
def devices() -> FakeDevices:
    return FakeDevices()


@pytest.fixture
def client(wakes: FakeWakes, devices: FakeDevices) -> Generator[TestClient]:
    app = create_app(Settings(database_url="", build_version="test"))
    services.register(Devices, devices)
    services.register(Wakes, wakes)
    yield TestClient(app)
    services.unregister(Devices)
    services.unregister(Wakes)


def post(client: TestClient, body: object, token: str | None = TOKEN,
         headers: dict[str, str] | None = None) -> tuple[int, object]:
    sent = {**({} if token is None else {"Authorization": f"Bearer {token}"}), **(headers or {})}
    got = client.post("/api/wakes", json=body, headers=sent)
    return got.status_code, got.json()


def test_a_wake_is_stored_as_its_fields_and_answered_202_at_once(client: TestClient, wakes: FakeWakes) -> None:
    status, got = post(client, BODY)
    assert status == 202 and WakeAccepted.model_validate(got) == WakeAccepted(id=1, duplicate=False)
    [(device_id, wake)] = wakes.got
    assert device_id == HOUSE.id
    assert wake == Wake(10, "01JBX3K7", "alana_arrived", "person.alana", "front_door",
                        datetime(2026, 11, 1, 0, 2, tzinfo=UTC))


def test_only_the_event_and_its_id_are_needed_and_when_defaults_to_now(client: TestClient, wakes: FakeWakes) -> None:
    before = datetime.now(UTC)
    status, _ = post(client, {"event_id": "e1", "event": "garage_open"})
    [(_, wake)] = wakes.got
    assert status == 202 and wake.who is None and wake.what is None and wake.at >= before


def test_the_same_event_id_again_is_202_duplicate_and_stores_nothing(client: TestClient, wakes: FakeWakes) -> None:
    post(client, BODY)
    status, got = post(client, {**BODY, "event": "garage_open"})
    assert status == 202 and WakeAccepted.model_validate(got) == WakeAccepted(id=1, duplicate=True)
    assert len(wakes.got) == 1


@pytest.mark.parametrize("change", [
    {"event": "Alana came home"}, {"event": ""}, {"who": "Alana"}, {"who": "person.alana and his mum"},
    {"what": "the front door"}, {"when": "just now"}, {"event_id": ""}, {"event_id": "x" * 129},
    {"note": "welcome him"}, {"event_id": None}])
def test_free_text_or_an_unknown_field_is_422_and_stores_nothing(client: TestClient, wakes: FakeWakes,
                                                                 change: dict[str, object]) -> None:
    status, _ = post(client, {k: v for k, v in {**BODY, **change}.items() if v is not None})
    assert status == 422 and wakes.got == []


def test_no_token_a_wrong_one_or_a_public_request_is_401(client: TestClient, wakes: FakeWakes) -> None:
    assert post(client, BODY, token=None)[0] == 401
    assert post(client, BODY, token="nope")[0] == 401
    assert post(client, BODY, headers={"Cf-Connecting-IP": "203.0.113.9"})[0] == 401
    assert wakes.got == []


@pytest.mark.parametrize("token", sorted(OTHERS))
def test_a_device_that_is_not_the_house_is_403_and_stores_nothing(client: TestClient, wakes: FakeWakes,
                                                                   token: str) -> None:
    status, got = post(client, BODY, token=token)
    assert status == 403 and ErrorResponse.model_validate(got).code == "forbidden" and wakes.got == []


def test_a_device_over_its_rate_is_429(client: TestClient, wakes: FakeWakes, devices: FakeDevices) -> None:
    devices.over = True
    assert post(client, BODY)[0] == 429 and wakes.got == []


def test_wakes_out_of_reach_is_503(client: TestClient, wakes: FakeWakes) -> None:
    wakes.down = True
    status, got = post(client, BODY)
    assert status == 503 and ErrorResponse.model_validate(got).code == "unavailable"


def test_the_log_carries_ids_never_a_field_of_the_wake(client: TestClient,
                                                       capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    post(client, BODY)
    post(client, BODY)
    out = capsys.readouterr().out
    got = events(out, "wakes.received")
    assert [g["duplicate"] for g in got] == ["false", "true"] and all(g["device"] == str(HOUSE.id) for g in got)
    for line in (line for line in out.splitlines() if "event=wakes." in line):
        for value in ("alana", "front_door", "01JBX3K7", "18:02"):
            assert value not in line
