"""The kiosk routes through the real app, with fakes behind the locator: pairing with a device token into its own cookie,
the device rule (public requests refused), the two cookies never standing in for each other, the Inbound built for the
device, what is counted against its rate, the glance carrying household names only, and controls run through Tools."""

from collections.abc import Generator
from dataclasses import dataclass, field, replace
from typing import Protocol

import pytest
from ashley import services
from ashley.api.kiosk import inbound_from
from ashley.api.kiosk_device import KIOSK_COOKIE
from ashley.api import live as live_route
from ashley.api.live_models import LiveEvent, LiveResync, LiveState
from ashley.api.models import ChatReply, ChatRequest, ErrorResponse, KioskControlDone, KioskDevice, KioskGlance
from ashley.api.person import SESSION_COOKIE
from ashley.channels.devices import Devices, DevicesUnavailable
from ashley.channels.kiosk.controls import Control
from ashley.channels.model import Device, DiscordServer, Inbound, Listed, Satellite
from ashley.conversations.conversations import Conversations
from ashley.conversations.inflight import InFlight
from ashley.inference.inference import Inference
from ashley.inference.model import ToolCall, ToolResult
from ashley.inference.reply import Reply
from ashley.live.events import DeviceViewer, HerState, Shown
from ashley.live.fanout import RESYNC
from ashley.live.live import Live
from ashley.main import create_app
from ashley.people.people import People
from ashley.runs.runs import NullRuns, Runs
from ashley.senses.presence import Presence
from ashley.settings import Settings
from ashley.tools.tools import Tools
from ashley.workshop.workshop import Workshop
from fastapi.testclient import TestClient
from live_support import FakeLive
from device_controls_support import FakeScreenControls
from respond_support import ALANA, HOME, Fakes, wired as wired

PUBLIC = "https://ashley.test"
TOKEN = "zqKIOSK-9931"
DEVICE = Device(7, HOME.id, "hall tablet", "hallway", "present", "text", "chat")
class _Answer(Protocol):
    def json(self) -> object: ...


LIGHT = Control("hall-light", "Hall light", "light.turn_on", "light.zq_hall")


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
def live(monkeypatch: pytest.MonkeyPatch) -> Generator[FakeLive]:
    monkeypatch.setattr(live_route, "CONFIG", replace(live_route.CONFIG, heartbeat_s=0.05, stream_s=0.1))
    yield FakeLive()


@pytest.fixture
def devices() -> Generator[FakeDevices]:
    yield FakeDevices()
    services.unregister(Devices)
    services.unregister(Workshop)


def _app(wired: Fakes, devices: FakeDevices, cookie: str | None = TOKEN, live: FakeLive | None = None) -> TestClient:
    app = create_app(Settings(database_url="", build_version="test", public_url=PUBLIC))
    if live is None:
        services.unregister(Live)
    else:
        services.register(Live, live)
    for interface, fake in ((People, wired.people), (Presence, wired.presence), (Conversations, wired.conversations),
                            (Inference, wired.inference), (Tools, wired.tools), (Devices, devices),
                            (Workshop, FakeScreenControls({(DEVICE.id, DEVICE.household_id): (LIGHT,)})),
                            (InFlight, InFlight.null()), (Runs, NullRuns())):
        services.register(interface, fake)
    client = TestClient(app, base_url=PUBLIC, headers={"origin": PUBLIC})
    if cookie is not None:
        client.cookies.set(KIOSK_COOKIE, cookie)
    return client


@pytest.fixture
def client(wired: Fakes, devices: FakeDevices, live: FakeLive) -> TestClient:
    return _app(wired, devices, live=live)


def _code(response: _Answer) -> str:
    return ErrorResponse.model_validate(response.json()).code


def test_pairing_sets_a_strict_host_cookie_and_logs_only_the_device(
        wired: Fakes, devices: FakeDevices, capsys: pytest.CaptureFixture[str]) -> None:
    capsys.readouterr()
    response = _app(wired, devices, cookie=None).post("/api/kiosk/session", json={"token": TOKEN})
    out = capsys.readouterr().out
    assert response.status_code == 200
    assert KioskDevice.model_validate(response.json()) == KioskDevice(id=7, name="hall tablet", place="hallway")
    set_cookie = response.headers["set-cookie"]
    assert set_cookie.startswith(f"{KIOSK_COOKIE}={TOKEN};")
    assert all(part in set_cookie for part in ("HttpOnly", "Secure", "SameSite=strict", "Path=/"))
    assert "Domain" not in set_cookie
    assert "event=kiosk.paired device=7" in out and TOKEN not in out


def test_pairing_with_a_wrong_token_is_401_and_sets_nothing(wired: Fakes, devices: FakeDevices) -> None:
    response = _app(wired, devices, cookie=None).post("/api/kiosk/session", json={"token": "zqWRONG"})
    assert response.status_code == 401 and _code(response) == "unauthorized"
    assert "set-cookie" not in response.headers


def test_pairing_from_the_public_internet_is_401(wired: Fakes, devices: FakeDevices,
                                                  capsys: pytest.CaptureFixture[str]) -> None:
    capsys.readouterr()
    response = _app(wired, devices, cookie=None).post("/api/kiosk/session", json={"token": TOKEN},
                                                      headers={"Cf-Connecting-IP": "203.0.113.9"})
    out = capsys.readouterr().out
    assert response.status_code == 401 and "set-cookie" not in response.headers
    assert "event=api.device_refused device=7 reason=public" in out and "203.0.113.9" not in out


def test_pairing_from_another_site_is_403_before_the_token_is_read(wired: Fakes, devices: FakeDevices) -> None:
    response = _app(wired, devices, cookie=None).post("/api/kiosk/session", json={"token": TOKEN},
                                                      headers={"origin": "https://evil.test"})
    assert response.status_code == 403 and devices.asked == []


@pytest.mark.parametrize(("method", "path"), [("GET", "/api/kiosk/device"), ("GET", "/api/kiosk/glance"),
                                              ("GET", "/api/kiosk/conversation"), ("GET", "/api/kiosk/controls"),
                                              ("GET", "/api/kiosk/live"),
                                              ("POST", "/api/kiosk/messages"), ("POST", "/api/kiosk/controls/hall-light")])
def test_a_public_request_with_the_kiosk_cookie_is_401_and_not_counted(
        client: TestClient, wired: Fakes, devices: FakeDevices, method: str, path: str) -> None:
    response = client.request(method, path, json={"text": "hi"} if method == "POST" else None,
                              headers={"Cf-Connecting-IP": "203.0.113.9"})
    assert response.status_code == 401 and _code(response) == "unauthorized"
    assert devices.counted == [] and wired.conversations.calls == [] and wired.tools.called == []


def test_a_persons_session_cookie_is_not_a_kiosk(wired: Fakes, devices: FakeDevices) -> None:
    client = _app(wired, devices, cookie=None)
    client.cookies.set(SESSION_COOKIE, TOKEN)
    response = client.get("/api/kiosk/device")
    assert response.status_code == 401 and devices.asked == []


def test_a_persons_session_cookie_is_not_a_kiosk_on_the_live_feed(wired: Fakes, devices: FakeDevices, live: FakeLive) -> None:
    client = _app(wired, devices, cookie=None, live=live)
    client.cookies.set(SESSION_COOKIE, TOKEN)
    response = client.get("/api/kiosk/live")
    assert response.status_code == 401 and devices.asked == [] and live.viewers == []


@pytest.mark.parametrize("path", ["/api/chat/conversation", "/api/live"])
def test_the_kiosk_cookie_is_not_a_person(client: TestClient, devices: FakeDevices, path: str) -> None:
    response = client.get(path)
    assert response.status_code == 401 and devices.asked == []


def test_the_kiosk_live_feed_is_the_devices_own_events(client: TestClient, live: FakeLive) -> None:
    live.scripted = (HerState(Shown(HOME.id, None), "a1b2", "thinking", 180.0), RESYNC)
    with client.stream("GET", "/api/kiosk/live") as response:
        assert response.status_code == 200 and response.headers["content-type"].startswith("text/event-stream")
        lines = list(response.iter_lines())
    assert live.viewers == [DeviceViewer(HOME.id, DEVICE.id)]
    assert [LiveEvent.model_validate_json(line.removeprefix("data: ")).root for line in lines
            if line.startswith("data:")] == [LiveState(type="state", turn="a1b2", state="thinking", at_most_s=180.0),
                                             LiveResync(type="resync")]


def test_no_live_feed_is_503_so_the_kiosk_reads_for_itself(wired: Fakes, devices: FakeDevices) -> None:
    response = _app(wired, devices).get("/api/kiosk/live")
    assert response.status_code == 503 and _code(response) == "unavailable"


def test_a_revoked_device_unpairs_the_screen(wired: Fakes, devices: FakeDevices) -> None:
    response = _app(wired, devices, cookie="zqREVOKED").get("/api/kiosk/device")
    assert response.status_code == 401 and devices.asked == ["zqREVOKED"]


def test_devices_unreachable_is_503(client: TestClient, devices: FakeDevices) -> None:
    devices.down = True
    response = client.get("/api/kiosk/device")
    assert response.status_code == 503 and _code(response) == "unavailable"


def test_the_inbound_is_the_devices_shared_text_on_its_thread() -> None:
    assert inbound_from(DEVICE, ChatRequest(text="hi")) == Inbound(
        household_id=HOME.id, thread="device:7", text="hi", kind="chat", medium="text", audience="present",
        speaker_id=None, shared=True, place="hallway", channel="web", remembers=True, heard_as=None, later=True,
        later_by="turn", device_id=7)


def test_a_message_gets_her_answer_and_is_counted(client: TestClient, wired: Fakes, devices: FakeDevices,
                                                  capsys: pytest.CaptureFixture[str]) -> None:
    wired.inference.script = [Reply(spoken="zqREPLY.", text="zqREPLY!")]
    capsys.readouterr()
    response = client.post("/api/kiosk/messages", json={"text": "zqSAID"})
    out = capsys.readouterr().out
    assert response.status_code == 200
    assert ChatReply.model_validate(response.json()) == ChatReply(conversation_id=1, body="zqREPLY!", follows=False)
    assert devices.counted == [7]
    assert wired.conversations.calls[0] == ("for_thread", (HOME.id, "device:7", "chat", ()))
    assert wired.contexts[0].place == "hallway"
    assert not [mark for mark in ("zqSAID", "zqREPLY", TOKEN) if mark in out]


def test_a_device_over_its_rate_is_429_before_she_is_asked(client: TestClient, wired: Fakes,
                                                           devices: FakeDevices) -> None:
    devices.over = True
    response = client.post("/api/kiosk/messages", json={"text": "hi"})
    assert response.status_code == 429 and _code(response) == "rate_limited" and wired.conversations.calls == []


def test_a_write_from_another_site_is_403_and_not_counted(client: TestClient, devices: FakeDevices) -> None:
    response = client.post("/api/kiosk/messages", json={"text": "hi"}, headers={"origin": "https://evil.test"})
    assert response.status_code == 403 and devices.counted == [] and devices.asked == []


def test_the_pages_reads_are_not_counted(client: TestClient, devices: FakeDevices) -> None:
    for path in ("/api/kiosk/device", "/api/kiosk/conversation", "/api/kiosk/glance", "/api/kiosk/controls"):
        assert client.get(path).status_code == 200, path
    assert devices.counted == []


def test_the_glance_names_only_the_household_people_home(client: TestClient, wired: Fakes) -> None:
    wired.presence.answer = frozenset({ALANA.id, 99})
    body = client.get("/api/kiosk/glance").json()
    assert KioskGlance.model_validate(body) == KioskGlance(home=["Alana"], not_connected=["calendar", "reminders"],
                                                           locale="en-US", clock="24h")
    assert set(body) == {"home", "not_connected", "locale", "clock"}


def test_the_glance_says_unknown_when_presence_cannot_tell(client: TestClient, wired: Fakes) -> None:
    wired.presence.answer = None
    assert KioskGlance.model_validate(client.get("/api/kiosk/glance").json()).home is None


def test_the_glance_says_nobody_home_as_an_empty_list(client: TestClient, wired: Fakes) -> None:
    wired.presence.answer = frozenset()
    assert KioskGlance.model_validate(client.get("/api/kiosk/glance").json()).home == []


def test_a_control_runs_its_tool_by_code_and_is_counted(client: TestClient, wired: Fakes, devices: FakeDevices,
                                                        capsys: pytest.CaptureFixture[str]) -> None:
    assert client.get("/api/kiosk/controls").json() == {"controls": [{"name": "hall-light", "label": "Hall light"}]}
    capsys.readouterr()
    response = client.post("/api/kiosk/controls/hall-light")
    out = capsys.readouterr().out
    assert KioskControlDone.model_validate(response.json()).done is True
    assert [(c.name, dict(c.arguments)) for c in wired.tools.called] == [
        ("house_do", {"action": "light.turn_on", "ids": ["light.zq_hall"]})]
    assert wired.inference.prompts == [] and devices.counted == [7]
    assert "event=kiosk.control device=7 control=hall-light outcome=ok" in out and "zq_hall" not in out


def test_a_control_the_tool_refused_is_not_done(client: TestClient, wired: Fakes, monkeypatch: pytest.MonkeyPatch) -> None:
    async def refused(call: ToolCall) -> ToolResult:
        return ToolResult(call.id, "no", is_error=True)

    monkeypatch.setattr(wired.tools, "call", refused)
    assert client.post("/api/kiosk/controls/hall-light").json() == {"done": False}


def test_an_unknown_control_is_404_and_not_counted(client: TestClient, wired: Fakes, devices: FakeDevices) -> None:
    response = client.post("/api/kiosk/controls/zq-none")
    assert response.status_code == 404 and _code(response) == "not_found"
    assert wired.tools.called == [] and devices.counted == []


def test_the_glance_says_unknown_when_the_household_cannot_be_read(client: TestClient, wired: Fakes) -> None:
    wired.presence.answer = frozenset({ALANA.id})
    services.register(People, People.null())
    assert KioskGlance.model_validate(client.get("/api/kiosk/glance").json()).home is None


def test_a_nul_in_a_kiosk_message_is_422(client: TestClient, wired: Fakes) -> None:
    response = client.post("/api/kiosk/messages", json={"text": "a\u0000b"})
    assert response.status_code == 422 and wired.conversations.calls == []


def test_a_nul_in_a_pairing_token_is_422(wired: Fakes, devices: FakeDevices) -> None:
    response = _app(wired, devices, cookie=None).post("/api/kiosk/session", json={"token": "a\u0000b"})
    assert response.status_code == 422 and devices.asked == []


def test_a_validation_error_does_not_echo_the_pairing_token_back(wired: Fakes, devices: FakeDevices) -> None:
    token = "t" * 201
    response = _app(wired, devices, cookie=None).post("/api/kiosk/session", json={"token": token})
    assert response.status_code == 422 and token not in response.text
    assert all(set(error) == {"type", "loc", "msg"} for error in response.json()["detail"])
