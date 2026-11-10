"""A household line on the earlier-conversations wire: its author, the household's name as speaker, no brief."""

from collections.abc import Generator

import pytest
from ashley import services
from ashley.api.person import person_signed_in
from ashley.conversations.conversations import Conversations
from ashley.conversations.model import Carried, Conversation, Cursor, NewTurn, Page, Turn
from ashley.main import create_app
from ashley.people.model import Household, Person
from ashley.people.people import People
from ashley.settings import Settings
from ashley.signin.model import SignedIn
from contract.conversations_support import household, person, run, service
from fastapi.testclient import TestClient
from ht_support import BRIEF, NAME, OnePerson

PUBLIC = "https://ashley.test"


class Stored(Conversations):
    def __init__(self, found: Conversation | None) -> None:
        self.found = found

    async def get(self, conversation_id: int) -> Conversation | None:
        return self.found

    async def start(self, *args: object, **kwargs: object) -> Conversation:
        raise AssertionError("reading starts none")

    async def add_turn(self, conversation_id: int, turn: NewTurn) -> Turn:
        raise AssertionError("reading adds no turn")

    async def for_thread(self, *args: object, **kwargs: object) -> Conversation:
        raise AssertionError("not used")

    async def on_thread(self, household_id: int, thread: str) -> Conversation | None:
        raise AssertionError("not used")

    async def of_person(self, household_id: int, person_id: int, limit: int, after: Cursor | None = None,
                        thread: str | None = None) -> Page:
        raise AssertionError("not used")

    async def answer_to(self, household_id: int, source: str) -> Turn | None:
        raise AssertionError("not used")

    async def spoken(self, *args: object, **kwargs: object) -> str | None:
        raise AssertionError("not used")

    async def carried(self, *args: object, **kwargs: object) -> Carried:
        raise AssertionError("not used")


@pytest.fixture
def client(db_url: str) -> Generator[tuple[TestClient, int, int]]:
    home = household(db_url, NAME)
    alana = person(db_url, home, "Alana")
    who = Person(alana, home, "Alana")
    out: dict[str, int] = {}
    stored: list[Conversation | None] = []

    async def seed() -> None:
        async with service(db_url) as conversations:
            started = await conversations.start(home, "chat", [alana])
            out["id"] = started.id
            await conversations.add_turn(started.id, NewTurn("household", "alana_arrived · Alana · front_door",
                                                              source="wake:1"))
            await conversations.add_turn(started.id, NewTurn("ashley", "Welcome home."))
            await conversations.add_turn(started.id, NewTurn("person", "thanks", alana, "private", alana))
            stored.append(await conversations.get(started.id))

    run(seed())
    app = create_app(Settings(database_url=db_url, build_version="t", public_url=PUBLIC))
    app.dependency_overrides[person_signed_in] = lambda: SignedIn(1, who)
    services.register(People, OnePerson(Household(home, NAME, "America/Denver", "", (who,))))

    services.register(Conversations, Stored(stored[0]))
    yield TestClient(app, base_url=PUBLIC), out["id"], alana


def test_a_household_line_has_the_household_author_and_its_name_as_speaker(client: tuple[TestClient, int, int]) -> None:
    http, cid, _ = client
    resp = http.get(f"/api/chat/conversations/{cid}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    lines = body["lines"]
    assert [(ln["author"], ln["speaker"]) for ln in lines] == [("household", NAME), ("ashley", None), ("person", "Alana")]
    assert lines[0]["text"] == "alana_arrived · Alana · front_door"


def test_no_brief_text_is_on_the_wire(client: tuple[TestClient, int, int]) -> None:
    http, cid, _ = client
    raw = http.get(f"/api/chat/conversations/{cid}").text
    assert BRIEF not in raw and "worth_saying" not in raw
