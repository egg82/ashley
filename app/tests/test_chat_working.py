"""The conversation route says which of the person's turns she is still working on (`ChatConversationTurn.working`),
from the turn's work in `InFlight` and not from any text, so the page shows a resumed turn as pending rather than
missed. The store excludes a turn already answered (`InFlight.working`)."""

from collections.abc import Generator
from dataclasses import dataclass, field, replace

import pytest
from ashley import services
from ashley.api.models import ChatConversation, ChatConversationTurn, ErrorResponse
from ashley.api.person import person_signed_in
from ashley.channels.outbox import Outbox
from ashley.conversations.conversations import Conversations
from ashley.conversations.inflight import InFlight, InFlightUnavailable, NullInFlight
from ashley.inference.inference import Inference
from ashley.inference.reply import Reply
from ashley.main import create_app
from ashley.people.people import People
from ashley.runs.runs import NullRuns, Runs
from ashley.settings import Settings
from ashley.signin.model import SignedIn
from fastapi.testclient import TestClient
from later_support import FakeOutbox
from respond_support import ALANA, Fakes, wired as wired

PUBLIC = "https://ashley.test"
REPLY = Reply(spoken="Done.", text="Done!")


@dataclass
class Working(NullInFlight):
    """Says `ids` are being worked on in every conversation; `down` makes it fail."""

    ids: frozenset[int] = field(default_factory=frozenset[int])
    down: bool = False

    async def working(self, conversation_id: int) -> frozenset[int]:
        if self.down:
            raise InFlightUnavailable("down")
        return self.ids


@pytest.fixture
def inflight() -> Generator[Working]:
    yield Working()
    services.unregister(InFlight)


@pytest.fixture
def client(wired: Fakes, inflight: Working) -> Generator[TestClient]:
    app = create_app(Settings(database_url="", build_version="test", public_url=PUBLIC))
    services.register(Outbox, FakeOutbox())
    services.register(People, wired.people)
    services.register(Runs, NullRuns())
    services.register(Conversations, wired.conversations)
    services.register(InFlight, inflight)
    services.register(Inference, wired.inference)
    app.dependency_overrides[person_signed_in] = lambda: SignedIn(1, ALANA)
    yield TestClient(app, base_url=PUBLIC, headers={"origin": PUBLIC})
    services.unregister(Outbox)


def conversation(client: TestClient) -> ChatConversation:
    response = client.get("/api/chat/conversation")
    assert response.status_code == 200
    return ChatConversation.model_validate(response.json())


def asked(client: TestClient, wired: Fakes, inflight: Working) -> list[ChatConversationTurn]:
    """The turns after one message, answered; none is working yet."""
    wired.inference.script = [REPLY]
    assert client.post("/api/chat/messages", json={"text": "lights on"}).status_code == 200
    return conversation(client).turns


def test_a_turn_is_not_working_when_nothing_is_in_flight(client: TestClient, wired: Fakes, inflight: Working) -> None:
    assert [t.working for t in asked(client, wired, inflight)] == [False, False]


def test_a_person_turn_with_work_in_flight_and_no_answer_is_working(client: TestClient, wired: Fakes,
                                                                   inflight: Working) -> None:
    turns = asked(client, wired, inflight)
    cid = wired.conversations.threads[f"person:{ALANA.id}:web"]
    conv = wired.conversations.convs[cid]
    wired.conversations.convs[cid] = replace(conv, turns=conv.turns[:1])  # her answer is not stored
    inflight.ids = frozenset({turns[0].id})
    got = conversation(client).turns
    assert [(t.author, t.working) for t in got] == [("person", True)]


def test_the_conversation_is_503_when_the_work_cannot_be_read(client: TestClient, wired: Fakes,
                                                              inflight: Working) -> None:
    asked(client, wired, inflight)
    inflight.down = True
    response = client.get("/api/chat/conversation")
    assert response.status_code == 503 and ErrorResponse.model_validate(response.json()).code == "unavailable"
