"""POST /api/messages through the real app, with fakes behind the locator: bearer sign-in, the thread and Inbound built
from the device, each declared status and body, and nothing of the body in the logs."""

from dataclasses import dataclass, field

import pytest
from ashley import services
from ashley.api.models import ErrorResponse, MessageResponse
from ashley.channels.devices import Devices, DevicesUnavailable
from ashley.channels.model import Device, DiscordServer, Listed, Satellite
from ashley.conversations.conversations import Conversations
from ashley.conversations.inflight import InFlight
from ashley.inference.inference import Inference, InferenceRefused, InferenceUnavailable
from ashley.inference.reply import Reply
from ashley.main import create_app
from ashley.people.people import People
from ashley.settings import Settings
from fastapi.testclient import TestClient
from respond_support import Fakes, wired as wired

TOKEN = "zqTOKEN-4471"
DEVICE = Device(7, 10, "tablet", "hallway", "present", "spoken", "chat")
REPLY = Reply(spoken="Done.", text="Done!")


@dataclass
class FakeDevices(Devices):
    down: bool = False
    over: bool = False
    counted: list[int] = field(default_factory=list[int])
    asked: list[str] = field(default_factory=list[str])

    async def by_token(self, token: str) -> Device | None:
        self.asked.append(token)
        if self.down:
            raise DevicesUnavailable("down")
        return DEVICE if token == TOKEN else None

    async def allow(self, device_id: int) -> bool:
        self.counted.append(device_id)
        return not self.over

    async def satellites(self) -> list[Satellite]:
        return []

    async def discord_servers(self) -> list[DiscordServer]:
        return []

    async def of_household(self, household_id: int) -> list[Listed]:
        return []


@pytest.fixture
def devices() -> FakeDevices:
    return FakeDevices()


@pytest.fixture
def client(wired: Fakes, devices: FakeDevices) -> TestClient:
    app = create_app(Settings(database_url="", build_version="test"))
    services.register(People, wired.people)
    services.register(Conversations, wired.conversations)
    services.register(InFlight, InFlight.null())
    services.register(Inference, wired.inference)
    services.register(Devices, devices)
    return TestClient(app)


def post(client: TestClient, body: object, token: str | None = TOKEN, scheme: str = "Bearer") -> tuple[int, object]:
    headers = {} if token is None else {"Authorization": f"{scheme} {token}"}
    response = client.post("/api/messages", json=body, headers=headers)
    return response.status_code, response.json()


def test_a_signed_in_device_gets_her_reply_for_its_medium(client: TestClient, wired: Fakes) -> None:
    wired.inference.script = [REPLY]
    status, body = post(client, {"text": "lights on"})
    assert status == 200
    assert MessageResponse.model_validate(body) == MessageResponse(conversation_id=1, medium="spoken", body="Done.")
    assert wired.conversations.calls[0] == ("for_thread", (10, "device:7", "chat", ()))
    assert wired.contexts[0].place == "hallway"
    assert wired.conversations.opened == {1: ("device", "hallway")}


def test_a_named_thread_is_kept_apart(client: TestClient, wired: Fakes) -> None:
    wired.inference.script = [REPLY]
    assert post(client, {"text": "hi", "thread": "probe_2"})[0] == 200
    assert wired.conversations.calls[0][1] == (10, "device:7:probe_2", "chat", ())


@pytest.mark.parametrize(("token", "scheme"), [(None, "Bearer"), ("wrong", "Bearer"), (TOKEN, "Basic"), ("", "Bearer")])
def test_no_device_is_401_before_anything_is_read(client: TestClient, wired: Fakes, token: str | None,
                                                  scheme: str) -> None:
    status, body = post(client, {"text": ""}, token, scheme)
    assert status == 401 and ErrorResponse.model_validate(body).code == "unauthorized"
    assert wired.conversations.calls == []


@pytest.mark.parametrize("body", [{}, {"text": ""}, {"text": "   "}, {"text": "x" * 4001}, {"text": "hi", "extra": 1},
                                  {"text": "hi", "thread": "a b"}, {"text": "hi", "thread": ""}])
def test_a_body_outside_the_request_model_is_422(client: TestClient, wired: Fakes, body: object) -> None:
    status, got = post(client, body)
    assert status == 422 and isinstance(got, dict) and "detail" in got
    assert wired.conversations.calls == []


@pytest.mark.parametrize(("error", "status", "code"), [(InferenceRefused("no"), 422, "refused"),
                                                       (InferenceUnavailable("no"), 503, "unavailable")])
def test_a_reply_that_fails_is_a_declared_error(client: TestClient, wired: Fakes, error: Exception, status: int,
                                                code: str) -> None:
    wired.inference.script = [error]
    got_status, body = post(client, {"text": "hi"})
    assert got_status == status and ErrorResponse.model_validate(body).code == code


def test_devices_unreachable_is_503(client: TestClient, devices: FakeDevices) -> None:
    devices.down = True
    status, body = post(client, {"text": "hi"})
    assert status == 503 and ErrorResponse.model_validate(body).code == "unavailable"


def test_nothing_of_the_body_or_token_is_logged(client: TestClient, wired: Fakes,
                                                capsys: pytest.CaptureFixture[str]) -> None:
    wired.inference.script = [Reply(spoken="zqREPLY", text="zqREPLY")]
    capsys.readouterr()
    post(client, {"text": "zqSAID secret", "thread": "zqTHREAD"})
    post(client, {"text": "zqSAID"}, "zqBADTOKEN")
    out = capsys.readouterr().out
    assert "route=/api/messages" in out
    assert not [mark for mark in ("zqSAID", "zqTHREAD", "zqREPLY", "zqBADTOKEN", TOKEN) if mark in out]


def test_a_device_token_from_the_public_internet_is_401_and_not_counted(
        client: TestClient, wired: Fakes, devices: FakeDevices, capsys: pytest.CaptureFixture[str]) -> None:
    capsys.readouterr()
    response = client.post("/api/messages", json={"text": "hi"},
                           headers={"Authorization": f"Bearer {TOKEN}", "Cf-Connecting-IP": "203.0.113.9"})
    out = capsys.readouterr().out
    assert response.status_code == 401 and ErrorResponse.model_validate(response.json()).code == "unauthorized"
    assert wired.conversations.calls == [] and devices.counted == []
    assert "event=api.device_refused device=7 reason=public" in out
    assert TOKEN not in out and "203.0.113.9" not in out


def test_a_device_over_its_rate_is_429(client: TestClient, wired: Fakes, devices: FakeDevices,
                                       capsys: pytest.CaptureFixture[str]) -> None:
    devices.over = True
    capsys.readouterr()
    status, body = post(client, {"text": "hi"})
    out = capsys.readouterr().out
    assert status == 429 and ErrorResponse.model_validate(body).code == "rate_limited"
    assert wired.conversations.calls == [] and devices.counted == [7]
    assert "event=api.device_refused device=7 reason=rate" in out and TOKEN not in out


def test_a_non_answer_is_asked_again_and_the_answer_is_the_response(client: TestClient, wired: Fakes) -> None:
    wired.inference.script = [Reply(answers=False, spoken="Let me check.", text="Let me check."), REPLY]
    status, body = post(client, {"text": "is it raining"})
    assert status == 200
    assert MessageResponse.model_validate(body).body == "Done."
    assert [p.tool_choice for p in wired.inference.prompts] == ["auto", "auto"]


def test_a_nul_in_a_device_message_is_422(client: TestClient, wired: Fakes) -> None:
    status, _ = post(client, {"text": "a\u0000b"})
    assert status == 422 and wired.conversations.calls == []
