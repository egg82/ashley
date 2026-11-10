"""The three conversation routes over fakes: her conversation stored as given, the runs served by a recording
Runs. One `Surface` per route, so each test runs on web chat, a bench's talk and the kiosk."""

from collections.abc import Callable, Generator, Sequence
from dataclasses import dataclass, field

import psycopg
import pytest
from ashley import services
from ashley.api.kiosk_device import KIOSK_COOKIE
from ashley.api.models import ChatConversation
from ashley.api.person import person_signed_in
from ashley.channels.devices import Devices
from ashley.channels.model import Device, DiscordServer, Listed, Satellite
from ashley.conversations.conversations import Conversations
from ashley.conversations.inflight import InFlight
from ashley.conversations.model import Carried, Conversation, Cursor, NewTurn, Page, Turn
from ashley.live.live import Live
from ashley.main import create_app
from ashley.people.people import People
from ashley.runs.model import Run
from ashley.runs.runs import NullRuns, Runs, RunsUnavailable
from ashley.settings import Settings
from ashley.signin.model import SignedIn
from cr_support import AT
from fastapi.testclient import TestClient
from httpx2 import Response
from respond_support import ALANA, HOME, Fakes

PUBLIC = "https://ashley.test"
TOKEN = "zqKIOSK-9931"
DEVICE = Device(7, HOME.id, "hall tablet", "hallway", "present", "text", "chat")
CONVERSATION_ID = 5


@dataclass
class StoredConversation(Conversations):
    turns: tuple[Turn, ...] = ()

    async def _read(self) -> Conversation:
        return Conversation(CONVERSATION_ID, HOME.id, "chat", frozenset({ALANA.id}), AT, AT, "open", self.turns)

    async def get(self, conversation_id: int) -> Conversation | None:
        return await self._read()

    async def answer_to(self, household_id: int, source: str) -> Turn | None:
        raise AssertionError("not used")

    async def on_thread(self, household_id: int, thread: str) -> Conversation | None:
        return await self._read()

    async def start(self, *args: object, **kwargs: object) -> Conversation:
        raise AssertionError("reading starts none")

    async def add_turn(self, conversation_id: int, turn: NewTurn) -> Turn:
        raise AssertionError("reading adds no turn")

    async def for_thread(self, *args: object, **kwargs: object) -> Conversation:
        raise AssertionError("reading points no thread")

    async def of_person(self, household_id: int, person_id: int, limit: int, after: Cursor | None = None,
                        thread: str | None = None) -> Page:
        raise AssertionError("not used")

    async def spoken(self, *args: object, **kwargs: object) -> str | None:
        raise AssertionError("not used")

    async def carried(self, *args: object, **kwargs: object) -> Carried:
        raise AssertionError("not used")


@dataclass
class RecordingRuns(NullRuns):
    runs: Sequence[Run] = ()
    asked: list[tuple[int, int]] = field(default_factory=list[tuple[int, int]])
    down: bool = False

    async def in_conversation(self, household_id: int, conversation_id: int) -> list[Run]:
        self.asked.append((household_id, conversation_id))
        if self.down:
            raise RunsUnavailable("down")
        return list(self.runs)


class Devices1(Devices):
    async def by_token(self, token: str) -> Device | None:
        return DEVICE if token == TOKEN else None

    async def allow(self, device_id: int) -> bool:
        return True

    async def satellites(self) -> list[Satellite]:
        return []

    async def discord_servers(self) -> list[DiscordServer]:
        return []

    async def of_household(self, household_id: int) -> list[Listed]:
        return []


@dataclass
class Surface:
    """One route: `read` serves the conversation of `turns` with `runs` and gives the response."""

    name: str
    open_: Callable[[StoredConversation, RecordingRuns], TestClient]
    path: Callable[[], str]
    stored: StoredConversation = field(default_factory=StoredConversation)
    runs: RecordingRuns = field(default_factory=RecordingRuns)
    client: TestClient | None = None

    def read(self, turns: Sequence[Turn], runs: Sequence[Run] = (), down: bool = False) -> Response:
        self.stored.turns, self.runs.runs, self.runs.down = tuple(turns), runs, down
        if self.client is None:
            self.client = self.open_(self.stored, self.runs)
        return self.client.get(self.path())

    def conversation(self, turns: Sequence[Turn], runs: Sequence[Run] = ()) -> ChatConversation:
        got = self.read(turns, runs)
        assert got.status_code == 200
        return ChatConversation.model_validate(got.json())


def register(wired: Fakes, stored: Conversations, runs: Runs) -> None:
    services.register(People, wired.people)
    services.register(Conversations, stored)
    services.register(Runs, runs)
    services.register(InFlight, InFlight.null())


def chat(wired: Fakes, stored: StoredConversation, runs: RecordingRuns) -> TestClient:
    app = create_app(Settings(database_url="", build_version="t", public_url=PUBLIC))
    register(wired, stored, runs)
    app.dependency_overrides[person_signed_in] = lambda: SignedIn(1, ALANA)
    return TestClient(app, base_url=PUBLIC)


def kiosk(wired: Fakes, stored: StoredConversation, runs: RecordingRuns) -> TestClient:
    app = create_app(Settings(database_url="", build_version="t", public_url=PUBLIC))
    services.unregister(Live)
    register(wired, stored, runs)
    services.register(Devices, Devices1())
    client = TestClient(app, base_url=PUBLIC, headers={"origin": PUBLIC})
    client.cookies.set(KIOSK_COOKIE, TOKEN)
    return client


def bench(url: str, wired: Fakes, made_id: list[int]) -> Callable[[StoredConversation, RecordingRuns], TestClient]:
    def open_bench(stored: StoredConversation, runs: RecordingRuns) -> TestClient:
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute("INSERT INTO households (id, name) OVERRIDING SYSTEM VALUE VALUES (%s, 'home')", (HOME.id,))
            conn.execute("INSERT INTO people (id, household_id, name) OVERRIDING SYSTEM VALUE VALUES (%s, %s, 'x')",
                         (ALANA.id, HOME.id))
        app = create_app(Settings(database_url=url, build_version="t", public_url=PUBLIC))
        client = TestClient(app, base_url=PUBLIC, headers={"origin": PUBLIC})
        client.__enter__()
        register(wired, stored, runs)
        app.dependency_overrides[person_signed_in] = lambda: SignedIn(1, ALANA)
        made = client.post("/api/benches", json={"title": "desk"})
        assert made.status_code == 200
        made_id.append(int(made.json()["id"]))
        return client

    return open_bench


SURFACES = ("chat", "bench", "kiosk")


@pytest.fixture(params=SURFACES)
def surface(request: pytest.FixtureRequest, wired: Fakes) -> Generator[Surface]:
    if request.param == "chat":
        made = Surface("chat", lambda s, r: chat(wired, s, r), lambda: "/api/chat/conversation")
    elif request.param == "kiosk":
        made = Surface("kiosk", lambda s, r: kiosk(wired, s, r), lambda: "/api/kiosk/conversation")
    else:
        url = request.getfixturevalue("db_url")
        bench_id: list[int] = []
        made = Surface("bench", bench(url, wired, bench_id), lambda: f"/api/benches/{bench_id[0]}/conversation")
    yield made
    if made.client is not None and request.param == "bench":
        made.client.__exit__(None, None, None)
    for interface in (People, Conversations, Runs, Devices, InFlight):
        services.unregister(interface)
