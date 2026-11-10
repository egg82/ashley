"""`POST /api/memory/remembered` through the real app and a real database, with a scripted `FactWriter` behind the
locator: a line of a conversation the person took part in is remembered and what changed comes back as their facts;
anyone else's conversation, or a turn not in it, is 404 exactly as one that does not exist, and the writer never runs."""

from collections.abc import Generator, Sequence
from dataclasses import dataclass
from datetime import datetime

import pytest
from ashley import logs, services
from ashley.api.models import ErrorResponse, RememberResponse
from ashley.api.person import person_signed_in
from ashley.conversations.model import Conversation
from ashley.inference.inference import InferenceRefused, InferenceRejected, InferenceUnavailable
from ashley.main import create_app
from ashley.memory.memory import FactWriter
from ashley.memory.model import Add, Fact, Invalidate, NewFact, Op, Visibility
from ashley.people.model import Person
from ashley.settings import Settings
from ashley.signin.model import SignedIn
from contract.conversations_support import db_url as db_url, events, migrated_template as migrated_template
from contract.conversations_support import household, person, scalar
from contract.memory_support import conversation, say
from fastapi.testclient import TestClient

PUBLIC = "https://ashley.test"


class Writer(FactWriter):
    """Answers `ops` (or raises `error`); records the turn ids of each conversation it was asked about."""

    def __init__(self) -> None:
        self.ops: tuple[Op, ...] = ()
        self.error: Exception | None = None
        self.seen: list[tuple[int, ...]] = []

    async def decide(self, conversation: Conversation, known: Sequence[Fact], now: datetime) -> tuple[Op, ...]:
        self.seen.append(tuple(t.id for t in conversation.turns))
        if self.error is not None:
            raise self.error
        return self.ops


@dataclass
class Home:
    url: str
    id: int
    alana: int
    ella: int
    alanas: int
    ellas: int
    alana_turns: tuple[int, ...]
    ella_turns: tuple[int, ...]


@pytest.fixture
def home(db_url: str) -> Home:
    hid = household(db_url)
    alana, ella = person(db_url, hid, "Alana"), person(db_url, hid, "Ella")
    talks: list[int] = []
    turns: list[tuple[int, ...]] = []
    for who in (alana, ella):
        made = conversation(db_url, hid)
        scalar(db_url, "INSERT INTO conversation_participants VALUES (%s, %s, %s) RETURNING person_id", (made, hid, who))
        talks.append(made)
        turns.append(say(db_url, made, "the cat is called Mochi", "Mochi, noted", speaker=who))
    return Home(db_url, hid, alana, ella, talks[0], talks[1], turns[0], turns[1])


@pytest.fixture
def writer() -> Generator[Writer]:
    w = Writer()
    yield w
    services.unregister(FactWriter)


@pytest.fixture
def client(home: Home, writer: Writer) -> Generator[TestClient]:
    app = create_app(Settings(database_url=home.url, build_version="t", public_url=PUBLIC))
    services.register(FactWriter, writer)
    app.dependency_overrides[person_signed_in] = lambda: SignedIn(1, Person(home.alana, home.id, "Alana"))
    with TestClient(app, base_url=PUBLIC, headers={"origin": PUBLIC}) as c:
        yield c


def about(who: int | None, text: str, visibility: Visibility = "shared") -> Add:
    return Add(NewFact(who, who, visibility, visibility != "shared", "home", False, text))


def facts(url: str) -> int:
    return int(scalar(url, "SELECT count(*) FROM facts"))


def test_a_line_of_their_own_conversation_is_remembered_and_comes_back_as_their_facts(
        client: TestClient, home: Home, writer: Writer, capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    writer.ops = (about(None, "The cat is called Mochi"), about(home.ella, "Ella keeps a diary", "private"))
    capsys.readouterr()
    got = client.post("/api/memory/remembered", json={"conversation_id": home.alanas, "turn_id": home.alana_turns[0]})
    assert got.status_code == 200
    body = RememberResponse.model_validate(got.json())
    assert [f.text for f in body.facts] == ["The cat is called Mochi"]
    assert (body.unseen, body.ended) == (1, 0)
    assert body.facts[0].source.conversation_id == home.alanas
    assert writer.seen == [home.alana_turns[:1]]
    assert scalar(home.url, "SELECT written_turn_id FROM memory_writes WHERE conversation_id = %s",
                  (home.alanas,)) == home.alana_turns[0]
    out = capsys.readouterr().out
    (line,) = events(out, "memory.remembered")
    assert (line["conversation"], line["turn"], line["moved"], line["turns"]) == (
        str(home.alanas), str(home.alana_turns[0]), "true", "1")
    assert "Mochi" not in out and "diary" not in out


def test_nothing_new_is_an_empty_answer(client: TestClient, home: Home, writer: Writer) -> None:
    got = client.post("/api/memory/remembered", json={"conversation_id": home.alanas, "turn_id": home.alana_turns[1]})
    assert RememberResponse.model_validate(got.json()) == RememberResponse(facts=[], unseen=0, ended=0)
    assert writer.seen == [home.alana_turns]


def test_ending_a_fact_is_counted(client: TestClient, home: Home, writer: Writer) -> None:
    cat = scalar(home.url, "INSERT INTO facts (household_id, about_id, owner_id, visibility, visibility_stated, kind, "
                           "standing, text, source_conversation_id, valid_from) SELECT household_id, NULL, NULL, "
                           "'shared', false, 'home', false, 'The cat is Mochi', id, now() FROM conversations "
                           "WHERE id = %s RETURNING id", (home.alanas,))
    writer.ops = (Invalidate(int(cat)),)
    got = client.post("/api/memory/remembered", json={"conversation_id": home.alanas, "turn_id": home.alana_turns[1]})
    assert RememberResponse.model_validate(got.json()) == RememberResponse(facts=[], unseen=0, ended=1)
    assert scalar(home.url, "SELECT valid_to IS NOT NULL FROM facts WHERE id = %s", (cat,)) is True


def test_anything_not_theirs_is_404_and_the_writer_never_runs(client: TestClient, home: Home, writer: Writer) -> None:
    writer.ops = (about(None, "anything"),)
    for asked in ({"conversation_id": home.ellas, "turn_id": home.ella_turns[0]},
                  {"conversation_id": home.alanas, "turn_id": home.ella_turns[0]},
                  {"conversation_id": 999999, "turn_id": home.alana_turns[0]}):
        got = client.post("/api/memory/remembered", json=asked)
        assert got.status_code == 404, asked
        assert ErrorResponse.model_validate(got.json()).code == "not_found"
    assert writer.seen == []
    assert facts(home.url) == 0


@pytest.mark.parametrize(("error", "status", "code"), [(InferenceUnavailable("down"), 503, "unavailable"),
                                                       (InferenceRefused("no"), 422, "refused"),
                                                       (InferenceRejected("bad"), 422, "refused")])
def test_a_writer_that_cannot_answer_is_an_honest_error(client: TestClient, home: Home, writer: Writer,
                                                        error: Exception, status: int, code: str) -> None:
    writer.error = error
    got = client.post("/api/memory/remembered", json={"conversation_id": home.alanas, "turn_id": home.alana_turns[0]})
    assert (got.status_code, ErrorResponse.model_validate(got.json()).code) == (status, code)
    assert facts(home.url) == 0


@pytest.mark.parametrize("body", [{"conversation_id": 0, "turn_id": 1}, {"conversation_id": 1},
                                  {"conversation_id": 1, "turn_id": 1, "text": "x"}])
def test_a_body_outside_the_request_is_422(client: TestClient, body: dict[str, object], writer: Writer) -> None:
    assert client.post("/api/memory/remembered", json=body).status_code == 422
    assert writer.seen == []


def test_no_session_is_401_and_another_site_is_403(home: Home) -> None:
    app = create_app(Settings(database_url=home.url, build_version="t", public_url=PUBLIC))
    asked = {"conversation_id": home.alanas, "turn_id": home.alana_turns[0]}
    with TestClient(app, base_url=PUBLIC) as c:
        assert c.post("/api/memory/remembered", json=asked, headers={"origin": PUBLIC}).status_code == 401
        assert c.post("/api/memory/remembered", json=asked, headers={"origin": "https://evil.test"}).status_code == 403
