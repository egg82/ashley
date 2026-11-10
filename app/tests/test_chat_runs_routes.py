"""The runs on the conversation routes: web chat, a bench's talk and the kiosk read them from one place, each under her
answer; Runs unreachable is 503 like Conversations; a run of another conversation or household is never served."""

from collections.abc import Generator, Mapping, Sequence

import pytest
from ashley import services
from ashley.api.models import ChatConversation
from ashley.api.person import person_signed_in
from ashley.channels.outbox import Outbox
from ashley.conversations.conversations import Conversations
from ashley.conversations.inflight import InFlight
from ashley.inference.inference import Inference
from ashley.main import create_app
from ashley.people.people import People
from ashley.settings import Settings
from ashley.signin.model import SignedIn
from ashley.runs.model import Artifact, NewRun, Output, Run
from ashley.runs.runs import Runs, RunsUnavailable
from fastapi.testclient import TestClient
from later_support import FakeOutbox
from respond_support import ALANA, Fakes, wired as wired
from test_chat_routes import EPOCH, PUBLIC, REPLY, outbox as outbox, send


class Book(Runs):
    def __init__(self) -> None:
        self.runs: list[Run] = []
        self.down = False
        self.asked: list[tuple[int, int]] = []

    async def start(self, run: NewRun) -> int:
        raise NotImplementedError

    async def finish(self, run_id: int, output: Output, artifacts: Sequence[Artifact] = ()) -> Run:
        raise NotImplementedError

    async def get(self, household_id: int, run_id: int) -> Run | None:
        raise NotImplementedError

    async def of_turns(self, household_id: int, turn_ids: tuple[int, ...], latest: int) -> list[Run]:
        raise NotImplementedError

    async def last_on_bench(self, household_id: int, bench_id: int) -> Mapping[int, Run]:
        raise NotImplementedError

    async def files_left(self, household_id: int, bench_id: int, piece_id: int) -> Mapping[str, str]:
        raise NotImplementedError

    async def in_conversation(self, household_id: int, conversation_id: int) -> list[Run]:
        if self.down:
            raise RunsUnavailable("down")
        self.asked.append((household_id, conversation_id))
        return [r for r in self.runs if (r.household_id, r.conversation_id) == (household_id, conversation_id)]


def signed_in_client(wired: Fakes, outbox: FakeOutbox) -> TestClient:
    app = create_app(Settings(database_url="", build_version="test", public_url=PUBLIC))
    services.register(Outbox, outbox)
    services.register(People, wired.people)
    services.register(Conversations, wired.conversations)
    services.register(InFlight, InFlight.null())
    services.register(Inference, wired.inference)
    app.dependency_overrides[person_signed_in] = lambda: SignedIn(1, ALANA)
    return TestClient(app, base_url=PUBLIC, headers={"origin": PUBLIC})


@pytest.fixture
def book() -> Generator[Book]:
    got = Book()
    services.register(Runs, got)
    yield got
    services.unregister(Runs)


def ran(id: int, conversation: int, turn: int, home: int = ALANA.household_id) -> Run:
    return Run(id, home, conversation, turn, f"c{id}", "python", "print(1)", "", {}, EPOCH, EPOCH,
               Output("ran", 0, "1\n", ""))


def test_a_run_comes_with_her_answer_in_one_read(wired: Fakes, outbox: FakeOutbox, book: Book) -> None:
    client = signed_in_client(wired, outbox)
    services.register(Runs, book)
    wired.inference.script = [REPLY]
    send(client, "one plus none")
    asked = ChatConversation.model_validate(client.get("/api/chat/conversation").json()).turns[0].id
    book.runs = [ran(1, 1, asked), ran(2, 1, asked), ran(3, 2, asked), ran(4, 1, asked, home=ALANA.household_id + 1)]
    book.asked.clear()
    turns = ChatConversation.model_validate(client.get("/api/chat/conversation").json()).turns
    assert [len(t.runs) for t in turns] == [0, 2]
    assert [r.id for r in turns[1].runs] == [1, 2]
    assert turns[1].runs[0].stdout == "1\n" and turns[1].runs[0].result == "ran"
    assert book.asked == [(ALANA.household_id, 1)]


def test_the_conversation_is_503_when_the_runs_cannot_be_read(wired: Fakes, outbox: FakeOutbox, book: Book) -> None:
    client = signed_in_client(wired, outbox)
    services.register(Runs, book)
    wired.inference.script = [REPLY]
    send(client, "hi")
    book.down = True
    response = client.get("/api/chat/conversation")
    assert response.status_code == 503 and response.json()["code"] == "unavailable"
