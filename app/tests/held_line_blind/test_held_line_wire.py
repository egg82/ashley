"""The mark on the wire: both conversation routes serve `follows` on a turn, true on a held line and false elsewhere."""

from collections.abc import Generator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest
from ashley import services
from ashley.api.history_models import PastConversation, PastTurn
from ashley.api.models import ChatConversation, ChatTurn
from ashley.api.person import person_signed_in
from ashley.conversations.conversations import Conversations
from ashley.conversations.inflight import InFlight
from ashley.conversations.model import Carried, Conversation, Cursor, NewTurn, Page, Turn
from ashley.main import create_app
from ashley.runs.runs import NullRuns, Runs
from ashley.people.people import People
from ashley.settings import Settings
from ashley.signin.model import SignedIn
from fastapi.testclient import TestClient
from respond_support import ALANA, FakePeople

PUBLIC = "https://ashley.test"
AT = datetime(2026, 10, 27, 19, 42, tzinfo=UTC)


def _turn(i: int, author: str, text: str, follows: bool = False) -> Turn:
    return Turn(i, "ashley" if author == "ashley" else "person", None if author == "ashley" else ALANA.id, text,
                AT + timedelta(minutes=i), follows)


TURNS = (_turn(1, "person", "is it raining"), _turn(2, "ashley", "Let me check.", True),
         _turn(3, "ashley", "No rain today."))
OPEN = Conversation(5, ALANA.household_id, "chat", frozenset({ALANA.id}), AT, AT, "open", TURNS)
EXPECTED = [("person", "is it raining", False), ("ashley", "Let me check.", True), ("ashley", "No rain today.", False)]


@dataclass
class Fake(Conversations):
    stored: dict[int, Conversation] = field(default_factory=lambda: {5: OPEN})

    async def get(self, conversation_id: int) -> Conversation | None:
        return self.stored.get(conversation_id)

    async def answer_to(self, household_id: int, source: str) -> Turn | None:
        raise AssertionError("not used")

    async def on_thread(self, household_id: int, thread: str) -> Conversation | None:
        return OPEN

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


@pytest.fixture
def client() -> Generator[TestClient]:
    app = create_app(Settings(database_url="", build_version="t", public_url=PUBLIC))
    services.register(Conversations, Fake())
    services.register(Runs, NullRuns())
    services.register(InFlight, InFlight.null())
    services.register(People, FakePeople())
    app.dependency_overrides[person_signed_in] = lambda: SignedIn(1, ALANA)
    yield TestClient(app, base_url=PUBLIC)
    services.unregister(Conversations)
    services.unregister(Runs)
    services.unregister(InFlight)
    services.unregister(People)


def test_the_web_thread_serves_follows_on_each_turn(client: TestClient) -> None:
    got = ChatConversation.model_validate(client.get("/api/chat/conversation").json())
    assert [(t.author, t.text, t.follows) for t in got.turns] == EXPECTED


def test_an_earlier_conversation_serves_follows_on_each_line(client: TestClient) -> None:
    got = PastConversation.model_validate(client.get("/api/chat/conversations/5").json())
    assert [(t.author, t.text, t.follows) for t in got.lines] == EXPECTED


def test_the_raw_json_carries_a_follows_boolean_on_every_turn(client: TestClient) -> None:
    for turns in (client.get("/api/chat/conversation").json()["turns"],
                  client.get("/api/chat/conversations/5").json()["lines"]):
        assert [t["follows"] for t in turns] == [False, True, False]


def test_both_wire_turns_declare_follows_as_a_required_boolean() -> None:
    for model in (ChatTurn, PastTurn):
        assert model.model_fields["follows"].annotation is bool
        assert model.model_fields["follows"].is_required()
