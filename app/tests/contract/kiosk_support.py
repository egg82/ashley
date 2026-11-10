"""Fakes for the blind kiosk tests: a Devices that signs in one tablet by token, and the person-side fakes of
`web_chat_support`, behind the locator under the real app, with the tablet's controls held by a fake `Workshop` that answers `screen`."""

import sys
from collections.abc import Generator
from dataclasses import dataclass, field, replace
from typing import Any

import pytest
from ashley import services
from ashley.api import live as live_route
from ashley.channels import respond as respond_module
from ashley.channels.devices import Devices, DevicesUnavailable
from ashley.channels.kiosk.controls import Control
from ashley.channels.model import Device, DiscordServer, Listed, Satellite
from ashley.channels.outbox import Outbox
from ashley.conversations.conversations import Conversations
from ashley.conversations.inflight import InFlight
from ashley.runs.runs import NullRuns, Runs
from ashley.inference.model import ToolCall, ToolResult
from ashley.live.live import Live
from ashley.main import create_app
from ashley.people.model import Account, Household
from ashley.people.people import People, PeopleUnavailable
from ashley.senses.presence import Presence
from ashley.settings import Settings
from ashley.signin.sessions import Sessions
from ashley.tools.everyday import Everyday
from ashley.tools.tools import Catalogue, Tools
from ashley.workshop.workshop import Workshop
from device_controls_support import FakeScreenControls
from contract_support import OPENAPI, unreachable_conninfo
from fastapi.testclient import TestClient
from later_support import FakeOutbox
from live_support import FakeLive
from web_chat_support import (ALANA, COOKIE, ELLA, HOME, JSON, PUBLIC, TWELVE, FakeConversations, FakeSessions,
                              TurnLoop)

KIOSK_COOKIE = "__Host-ashley_kiosk"
TOKEN = "zqTOKEN-kiosk-5521"
MARK = "zqLEAK8830"
DEVICE = Device(9, HOME, "hallway tablet", "hallway", "present", "text", "chat")
HALL_LIGHT = Control("hall-light", "Hall light", "light.turn_on", "light.zq_hall")
NIGHT = Control("night", "Night", "scene.turn_on", "scene.zq_night")
LOCK_UP = Control("lock-up", "Lock up", "light.turn_off", "light.zq_porch")


@dataclass
class FakeDevices(Devices):
    """The tablet's token signs in `DEVICE` while it is in `by`; `over` makes `allow` say no; `counted` records `allow`."""

    by: dict[str, Device] = field(default_factory=lambda: {TOKEN: DEVICE})
    asked: list[str] = field(default_factory=list[str])
    counted: list[int] = field(default_factory=list[int])
    over: bool = False
    down: bool = False

    async def by_token(self, token: str) -> Device | None:
        self.asked.append(token)
        if self.down:
            raise DevicesUnavailable("down")
        return self.by.get(token)

    async def allow(self, device_id: int) -> bool:
        if self.down:
            raise DevicesUnavailable("down")
        self.counted.append(device_id)
        return not self.over

    async def satellites(self) -> list[Satellite]:
        return []

    async def discord_servers(self) -> list[DiscordServer]:
        return []

    async def of_household(self, household_id: int) -> list[Listed]:
        return []


@dataclass
class FakeTools(Tools):
    """Records each call; answers `result` unless the call's tool is in `failing`."""

    calls: list[ToolCall] = field(default_factory=list[ToolCall])
    failing: set[str] = field(default_factory=set[str])

    async def catalogue(self) -> Catalogue:
        return Catalogue((), None)

    async def call(self, call: ToolCall) -> ToolResult:
        self.calls.append(call)
        return ToolResult(call.id, f"result {MARK}", is_error=call.name in self.failing)


@dataclass
class FakePresence(Presence):
    """Who is home, as person ids; None is unknown."""

    at_home: frozenset[int] | None = frozenset()
    asked: list[int] = field(default_factory=list[int])

    async def home(self, household_id: int) -> frozenset[int] | None:
        self.asked.append(household_id)
        return self.at_home


@dataclass
class FakePeople(People):
    """One household of `ALANA`, `ELLA` and `TWELVE`, readable unless `down`."""

    down: bool = False

    async def household(self, household_id: int) -> Household | None:
        if self.down:
            raise PeopleUnavailable("down")
        return Household(HOME, "House", "America/Denver", "", (ALANA, ELLA, TWELVE)) if household_id == HOME else None

    async def person_for(self, system: str, external_id: str) -> Any:
        raise AssertionError("the kiosk never maps an account")

    async def accounts(self, household_id: int, system: str) -> tuple[Account, ...]:
        raise AssertionError("the kiosk never lists accounts")


SILENCE = (b"RIFF" + (36 + 8000).to_bytes(4, "little") + b"WAVEfmt " + (16).to_bytes(4, "little")
           + (1).to_bytes(2, "little") + (1).to_bytes(2, "little") + (16000).to_bytes(4, "little")
           + (32000).to_bytes(4, "little") + (2).to_bytes(2, "little") + (16).to_bytes(2, "little")
           + b"data" + (8000).to_bytes(4, "little") + bytes(8000))


@dataclass
class Kiosk:
    app: TestClient
    devices: FakeDevices
    device_controls: FakeScreenControls
    sessions: FakeSessions
    conversations: FakeConversations
    loop: TurnLoop
    tools: FakeTools
    presence: FakePresence
    people: FakePeople
    patch: pytest.MonkeyPatch

    def set_controls(self, *controls: Control) -> None:
        """The controls the tablet's own device shows."""
        self.device_controls.held[(DEVICE.id, DEVICE.household_id)] = controls

    def get(self, path: str, headers: dict[str, str] | None = None, token: str | None = TOKEN) -> Any:
        return self.app.get(path, headers={**self.cookie(token), **(headers or {})})

    def post(self, path: str, body: Any = None, headers: dict[str, str] | None = None,
             token: str | None = TOKEN) -> Any:
        if path.endswith("/transcripts"):   # takes a WAV, not JSON: a quarter second of silence
            wav = {"content-type": "audio/wav", "origin": PUBLIC}
            return self.app.post(path, content=SILENCE, headers={**wav, **self.cookie(token), **(headers or {})})
        sent = {"text": "hi"} if body is None and "messages" in path else ({} if body is None else body)
        return self.app.post(path, json=sent, headers={**JSON, **self.cookie(token), **(headers or {})})

    @staticmethod
    def cookie(token: str | None) -> dict[str, str]:
        return {} if token is None else {"cookie": f"{KIOSK_COOKIE}={token}"}

    def effects(self) -> tuple[int, int, int]:
        """What a refused request must not have done: turns run, tools called, requests counted."""
        return len(self.loop.seen), len(self.tools.calls), len(self.devices.counted)


@pytest.fixture
def kiosk(monkeypatch: pytest.MonkeyPatch) -> Generator[Kiosk]:
    app = create_app(Settings(database_url=unreachable_conninfo(), build_version="t", public_url=PUBLIC))
    sessions = FakeSessions(ALANA, ELLA, TWELVE)
    world = Kiosk(TestClient(app, base_url=PUBLIC), FakeDevices(), FakeScreenControls(), sessions,
                  FakeConversations(), TurnLoop(), FakeTools(), FakePresence(), FakePeople(), monkeypatch)
    world.set_controls(HALL_LIGHT, LOCK_UP)
    monkeypatch.setattr(live_route, "CONFIG", replace(live_route.CONFIG, heartbeat_s=0.05, stream_s=0.1))
    services.register(Live, FakeLive())   # a feed with nothing to say, ending on its own
    for service, fake in ((Devices, world.devices), (Workshop, world.device_controls), (Sessions, sessions), (Conversations, world.conversations),
                          (Outbox, FakeOutbox()), (Tools, world.tools), (Presence, world.presence),
                          (People, world.people), (Runs, NullRuns()), (InFlight, InFlight.null()), (Everyday, Everyday.null())):
        services.register(service, fake)
    original = respond_module.respond
    for module in list(sys.modules.values()):   # wherever the route bound the turn loop, it now reaches the fake
        if getattr(module, "respond", None) is original:
            monkeypatch.setattr(module, "respond", world.loop)
    try:
        yield world
    finally:
        for service in (Devices, Workshop, Sessions, Conversations, Outbox, Tools, Presence, People, Live, Runs, InFlight, Everyday):
            services.unregister(service)


def person_cookie(person_id: int = 1) -> dict[str, str]:
    return {"cookie": f"{COOKIE}=t-{person_id}"}


def kiosk_routes() -> list[tuple[str, str]]:
    """Every (method, path) the served contract declares under /api/kiosk, a control's name filled in."""
    found = [(method.upper(), path.replace("{name}", HALL_LIGHT.id))
             for path, methods in OPENAPI["paths"].items() if path.startswith("/api/kiosk/")
             for method in methods]
    assert len(found) >= 7, "the contract declares the seven kiosk routes"
    return found


def cookie_routes() -> list[tuple[str, str]]:
    """The kiosk routes a paired screen's cookie opens: every one but pairing, which carries its token in the body."""
    return [(method, path) for method, path in kiosk_routes() if not path.endswith("/session")]


def reads() -> list[str]:
    """The kiosk's GET routes that answer 200 to a paired device for no input; one with a path id answers by what the id
    names (`test_voice_turns_routes`)."""
    return [path for method, path in kiosk_routes() if method == "GET" and "{" not in path]


def writes() -> list[tuple[str, dict[str, Any]]]:
    return [(path, body) for path, body in (("/api/kiosk/messages", {"text": "hi"}),
                                            (f"/api/kiosk/controls/{HALL_LIGHT.id}", {}))]


def call(world: Kiosk, method: str, path: str, **kwargs: Any) -> Any:
    if method == "GET":
        return world.get(path, **kwargs)
    body = {"token": TOKEN} if path.endswith("/session") else ({"text": "hi"} if path.endswith("messages") else {})
    return world.post(path, body, **kwargs)
