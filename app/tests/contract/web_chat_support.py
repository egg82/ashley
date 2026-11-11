"""Fakes for the blind web chat tests: sessions, conversations, outbox and a turn loop behind the locator, and the
`world` fixture that builds the real app over them."""

import sys
from collections.abc import Generator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from ashley import services
from ashley.api.models import ErrorResponse
from ashley.channels import respond as respond_module
from ashley.channels.model import Inbound, Outbound
from ashley.channels.outbox import Later, Outbox
from ashley.conversations.conversations import Conversations
from ashley.runs.runs import NullRuns, Runs
from ashley.conversations.inflight import InFlight
from ashley.conversations.model import Carried, Conversation, Cursor, Page, State, Turn
from ashley.main import create_app
from ashley.people.model import Person
from ashley.settings import Settings
from ashley.signin.model import LinkPending, SignedIn
from ashley.signin.sessions import Sessions, SessionsUnavailable
from contract_support import unreachable_conninfo
from fastapi.testclient import TestClient
from later_support import FakeOutbox

PUBLIC = "https://ashley.test"
COOKIE = "__Host-ashley_session"
HOME = 7
ALANA, ELLA, TWELVE = Person(1, HOME, "Alana"), Person(2, HOME, "Ella"), Person(12, HOME, "Twelve")
NOON = datetime(2026, 10, 25, 12, tzinfo=UTC)
JSON = {"content-type": "application/json", "origin": PUBLIC}
MARK = "zqLEAK4471"


class FakeSessions(Sessions):
    """Token `t-<id>` signs in person `<id>`; any other token is no session."""

    def __init__(self, *people: Person) -> None:
        self.by_token = {f"t-{p.id}": SignedIn(100 + p.id, p) for p in people}
        self.down = False

    async def find(self, token: str) -> SignedIn | None:
        if self.down:
            raise SessionsUnavailable("down")
        return self.by_token.get(token)

    async def begin(self, state: str, pending: Any) -> bool:
        raise AssertionError("not used")

    async def take(self, state: str) -> None:
        raise AssertionError("not used")

    async def open(self, system: str, external_id: str, admin_group: bool | None = None) -> None:
        raise AssertionError("not used")

    async def close(self, token: str) -> None:
        raise AssertionError("not used")

    async def refused(self, system: str, external_id: str, username: str) -> None:
        raise AssertionError("not used")

    async def begin_link(self, state: str, pending: LinkPending) -> bool:
        raise AssertionError("not used")

    async def take_link(self, state: str) -> LinkPending | None:
        raise AssertionError("not used")


@dataclass
class FakeConversations(Conversations):
    """What `on_thread` answers per (household, thread); every other call is a failure of the test."""

    by_thread: dict[tuple[int, str], Conversation] = field(default_factory=dict[tuple[int, str], Conversation])
    asked: list[tuple[int, str]] = field(default_factory=list[tuple[int, str]])
    error: Exception | None = None

    async def answer_to(self, household_id: int, source: str) -> Turn | None:
        raise AssertionError("not used")

    async def on_thread(self, household_id: int, thread: str) -> Conversation | None:
        self.asked.append((household_id, thread))
        if self.error is not None:
            raise self.error
        return self.by_thread.get((household_id, thread))

    async def start(self, *args: Any, **kwargs: Any) -> Conversation:
        raise AssertionError("reading the conversation starts none")

    async def add_turn(self, *args: Any, **kwargs: Any) -> Turn:
        raise AssertionError("reading the conversation adds no turn")

    async def for_thread(self, *args: Any, **kwargs: Any) -> Conversation:
        raise AssertionError("reading the conversation points no thread")

    async def get(self, conversation_id: int) -> Conversation | None:
        raise AssertionError("the route reads by thread")

    async def of_person(self, household_id: int, person_id: int, limit: int, after: Cursor | None = None,
                        thread: str | None = None) -> Page:
        raise AssertionError("not used")

    async def spoken(self, *args: Any, **kwargs: Any) -> str | None:
        raise AssertionError("not used")

    async def carried(self, *args: Any, **kwargs: Any) -> Carried:
        raise AssertionError("reading the conversation carries no turns")


@dataclass
class TurnLoop:
    """Stands in for `respond`: records each `Inbound`, then answers `reply` or raises `error`."""

    seen: list[Inbound] = field(default_factory=list[Inbound])
    reply: Outbound = field(default_factory=lambda: Outbound(55, "text", "hello Alana", False))
    error: Exception | None = None

    async def __call__(self, inbound: Inbound) -> Outbound:
        self.seen.append(inbound)
        if self.error is not None:
            raise self.error
        return self.reply


@dataclass
class World:
    app: TestClient
    sessions: FakeSessions
    conversations: FakeConversations
    outbox: FakeOutbox
    loop: TurnLoop

    def post(self, path: str, person: Person | None = ALANA, body: dict[str, Any] | None = None,
             headers: dict[str, str] | None = None) -> Any:
        sent = ({} if path.endswith("later") else {"text": "hi"}) if body is None else body
        return self.app.post(path, json=sent, headers={**JSON, **self._cookie(person), **(headers or {})})

    def get(self, person: Person | None = ALANA) -> Any:
        return self.app.get("/api/chat/conversation", headers=self._cookie(person))

    @staticmethod
    def _cookie(person: Person | None) -> dict[str, str]:
        return {} if person is None else {"cookie": f"{COOKIE}=t-{person.id}"}


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> Generator[World]:
    app = create_app(Settings(database_url=unreachable_conninfo(), build_version="t", public_url=PUBLIC))
    sessions = FakeSessions(ALANA, ELLA, TWELVE)
    conversations, outbox, loop = FakeConversations(), FakeOutbox(), TurnLoop()
    services.register(Sessions, sessions)
    services.register(Conversations, conversations)
    services.register(Runs, NullRuns())
    services.register(InFlight, InFlight.null())
    services.register(Outbox, outbox)
    original = respond_module.respond
    for module in list(sys.modules.values()):   # wherever the route bound the turn loop, it now reaches the fake
        if getattr(module, "respond", None) is original:
            monkeypatch.setattr(module, "respond", loop)
    try:
        yield World(TestClient(app, base_url=PUBLIC), sessions, conversations, outbox, loop)
    finally:
        services.unregister(Conversations)
        services.unregister(Runs)
        services.unregister(Outbox)


def turn(id_: int, author: str, text: str, minutes: int = 0) -> Turn:
    assert author in ("person", "ashley")
    return Turn(id_, "person" if author == "person" else "ashley", None, text, NOON + timedelta(minutes=minutes))


def conversation(id_: int, turns: tuple[Turn, ...], state: State = "open") -> Conversation:
    return Conversation(id_, HOME, "chat", frozenset({1}), NOON, NOON, state, turns)


def queue(world: World, person: Person, body: str, id_: int, follows: bool = False, thread: str | None = None) -> None:
    world.outbox.waiting.append(Later(id_, HOME, thread or f"person:{person.id}:web",
                                      Outbound(40 + id_, "text", body, follows), 900))


def error_of(response: Any) -> ErrorResponse:
    return ErrorResponse.model_validate(response.json())
