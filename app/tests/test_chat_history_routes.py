"""A person's earlier conversations through the real app, with fakes behind the locator: the list is theirs alone and
pages by an opaque cursor, one conversation reads with its speakers named, one they did not take part in is 404 exactly
as one that does not exist, and the logs carry ids and counts, never turns."""

from collections.abc import Generator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest
from ashley import services
from ashley.api.history import cursor_text, parse_cursor
from ashley.api.history_models import PastConversation, PastHistory
from ashley.api.models import ErrorResponse
from ashley.api.person import person_signed_in
from ashley.conversations.conversations import Conversations, ConversationsUnavailable
from ashley.conversations.model import Carried, Conversation, Cursor, NewTurn, Page, Summary, Turn
from ashley.main import create_app
from ashley.people.people import People
from ashley.settings import Settings
from ashley.signin.model import SignedIn
from fastapi.testclient import TestClient
from respond_support import ALANA, HOME, SAM, FakePeople

PUBLIC = "https://ashley.test"
AT = datetime(2026, 10, 27, 19, 42, tzinfo=UTC)


def _turns(*lines: tuple[str, int | None, str]) -> tuple[Turn, ...]:
    return tuple(Turn(i, "ashley" if who == "ashley" else "household" if who == "household" else "person", speaker, text,
                      AT + timedelta(minutes=i)) for i, (who, speaker, text) in enumerate(lines, 1))


MINE = Conversation(5, ALANA.household_id, "chat", frozenset({ALANA.id}), AT, AT, "closed",
                    _turns(("person", ALANA.id, "lights"), ("ashley", None, "done"), ("person", None, "who?")),
                    "device", "kitchen")
WOKEN = Conversation(8, ALANA.household_id, "chat", frozenset({ALANA.id}), AT, AT, "closed",
                     _turns(("household", None, "event alana_arrived; about Alana"), ("ashley", None, "Welcome home.")),
                     "device")
SAMS = Conversation(6, ALANA.household_id, "chat", frozenset({SAM.id}), AT, AT, "closed",
                    _turns(("person", SAM.id, "SECRET")))
FARAWAY = Conversation(7, 99, "chat", frozenset({ALANA.id}), AT, AT, "closed", _turns(("person", ALANA.id, "far")))


@dataclass
class FakeHistory(Conversations):
    """Lists newest id first for a person; `get` answers by id; every other call fails the test."""

    stored: dict[int, Conversation] = field(default_factory=dict[int, Conversation])
    asked: list[tuple[int, int, int, Cursor | None]] = field(default_factory=list[tuple[int, int, int, Cursor | None]])
    down: bool = False

    async def of_person(self, household_id: int, person_id: int, limit: int, after: Cursor | None = None,
                        thread: str | None = None) -> Page:
        self.asked.append((household_id, person_id, limit, after))
        if self.down:
            raise ConversationsUnavailable("down")
        mine = sorted((c for c in self.stored.values() if c.household_id == household_id and person_id in c.participants
                       and (after is None or c.id < after.id)), key=lambda c: -c.id)
        shown = tuple(Summary(c.id, c.kind, c.state, c.started_at, c.last_activity_at, c.channel, c.place, len(c.turns))
                      for c in mine[:limit])
        return Page(shown, Cursor(shown[-1].last_activity_at, shown[-1].id) if len(mine) > limit else None)

    async def get(self, conversation_id: int) -> Conversation | None:
        if self.down:
            raise ConversationsUnavailable("down")
        return self.stored.get(conversation_id)

    async def start(self, *args: object, **kwargs: object) -> Conversation:
        raise AssertionError("reading starts none")

    async def add_turn(self, conversation_id: int, turn: NewTurn) -> Turn:
        raise AssertionError("reading adds no turn")

    async def for_thread(self, *args: object, **kwargs: object) -> Conversation:
        raise AssertionError("reading points no thread")

    async def answer_to(self, household_id: int, source: str) -> Turn | None:
        raise AssertionError("not used")

    async def on_thread(self, household_id: int, thread: str) -> Conversation | None:
        raise AssertionError("not used")

    async def spoken(self, *args: object, **kwargs: object) -> str | None:
        raise AssertionError("not used")

    async def carried(self, *args: object, **kwargs: object) -> Carried:
        raise AssertionError("reading carries no turns")


@pytest.fixture
def conversations() -> FakeHistory:
    return FakeHistory({c.id: c for c in (MINE, SAMS, FARAWAY)})


@pytest.fixture
def client(conversations: FakeHistory) -> Generator[TestClient]:
    app = create_app(Settings(database_url="", build_version="t", public_url=PUBLIC))
    services.register(Conversations, conversations)
    services.register(People, FakePeople())
    app.dependency_overrides[person_signed_in] = lambda: SignedIn(1, ALANA)
    yield TestClient(app, base_url=PUBLIC)
    services.unregister(Conversations)
    services.unregister(People)


def test_the_list_is_the_signed_in_persons_own_in_their_household(client: TestClient, conversations: FakeHistory) -> None:
    got = PastHistory.model_validate(client.get("/api/chat/conversations").json())
    assert [(s.id, s.turn_count, s.channel, s.place) for s in got.conversations] == [(5, 3, "device", "kitchen")]
    assert got.next is None
    assert conversations.asked == [(ALANA.household_id, ALANA.id, 10, None)]


def test_a_page_hands_back_a_cursor_the_next_request_takes(client: TestClient, conversations: FakeHistory) -> None:
    conversations.stored[8] = MINE.__class__(8, MINE.household_id, "chat", MINE.participants, AT, AT, "closed", MINE.turns)
    first = PastHistory.model_validate(client.get("/api/chat/conversations?limit=1").json())
    assert [s.id for s in first.conversations] == [8] and first.next is not None
    second = PastHistory.model_validate(client.get("/api/chat/conversations", params={"limit": 1, "before": first.next}).json())
    assert [s.id for s in second.conversations] == [5] and second.next is None
    assert conversations.asked[1][3] == Cursor(AT, 8)


@pytest.mark.parametrize("before", ["junk", "20261027T194200000000-x", "99999999T000000000000-1", "-5"])
def test_a_cursor_no_page_returned_is_refused(client: TestClient, conversations: FakeHistory, before: str) -> None:
    response = client.get("/api/chat/conversations", params={"before": before})
    assert response.status_code == 422 and ErrorResponse.model_validate(response.json()).code == "refused"
    assert conversations.asked == []


@pytest.mark.parametrize("limit", [0, 51])
def test_a_limit_outside_one_to_fifty_is_refused(client: TestClient, limit: int) -> None:
    assert client.get("/api/chat/conversations", params={"limit": limit}).status_code == 422


def test_a_cursor_round_trips() -> None:
    cursor = Cursor(AT + timedelta(microseconds=123456), 42)
    assert parse_cursor(cursor_text(cursor)) == cursor


def test_one_conversation_reads_with_its_turns_and_who_said_them(client: TestClient) -> None:
    got = PastConversation.model_validate(client.get("/api/chat/conversations/5").json())
    assert (got.id, got.state, got.channel, got.place, got.turn_count) == (5, "closed", "device", "kitchen", 3)
    assert [(t.author, t.speaker, t.text) for t in got.lines] == [
        ("person", "Alana", "lights"), ("ashley", None, "done"), ("person", None, "who?")]


@pytest.mark.parametrize("ident", [6, 7, 404])
def test_a_conversation_they_did_not_take_part_in_is_404_the_same_as_one_that_does_not_exist(
        client: TestClient, ident: int) -> None:
    response = client.get(f"/api/chat/conversations/{ident}")
    assert response.status_code == 404
    assert response.json() == {"code": "not_found", "detail": "no such conversation"}


def test_it_is_read_only(client: TestClient) -> None:
    assert client.post("/api/chat/conversations/5", json={"text": "hi"}).status_code == 405


def test_conversations_down_is_503(client: TestClient, conversations: FakeHistory) -> None:
    conversations.down = True
    for path in ("/api/chat/conversations", "/api/chat/conversations/5"):
        response = client.get(path)
        assert response.status_code == 503 and response.json()["code"] == "unavailable"


def test_the_logs_carry_ids_and_counts_never_a_turn(client: TestClient, conversations: FakeHistory,
                                                    caplog: pytest.LogCaptureFixture) -> None:
    conversations.stored[5] = SAMS.__class__(5, SAMS.household_id, "chat", frozenset({ALANA.id}), AT, AT, "closed", SAMS.turns)
    with caplog.at_level("INFO"):
        client.get("/api/chat/conversations")
        client.get("/api/chat/conversations/5")
    text = " ".join(r.getMessage() for r in caplog.records)
    assert "chat.history" in text and "chat.past" in text and "SECRET" not in text


def test_a_turn_of_the_household_is_on_the_wire_spoken_by_the_households_name(client: TestClient,
                                                                         conversations: FakeHistory) -> None:
    conversations.stored[WOKEN.id] = WOKEN
    got = PastConversation.model_validate(client.get("/api/chat/conversations/8").json())
    assert [(t.author, t.speaker) for t in got.lines] == [("household", HOME.name), ("ashley", None)]
