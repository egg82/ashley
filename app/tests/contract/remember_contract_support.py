"""What the remember-a-line contract tests share: a household of two people and a conversation they took part in, a
scripted `FactWriter` behind the locator, and the app built as the memory route tests build it."""

from collections.abc import Generator, Sequence
from dataclasses import dataclass, field
from datetime import datetime

import psycopg
from ashley import services
from ashley.api.person import person_signed_in
from ashley.conversations.model import Conversation
from ashley.main import create_app
from ashley.memory.memory import FactWriter
from ashley.memory.model import Add, Fact, NewFact, Op, Visibility
from ashley.people import admin
from ashley.people.model import Person
from ashley.settings import Settings
from ashley.signin.model import SignedIn
from fastapi.testclient import TestClient
from httpx2 import Response

from conversations_support import scalar
from memory_support import conversation, say

PUBLIC = "https://ashley.test"
URL = "/api/memory/remembered"


def fact(text: str, about: int | None = None, owner: int | None = None, visibility: Visibility = "shared") -> Add:
    return Add(NewFact(about, owner, visibility, True, "preference", False, text))


class Scripted(FactWriter):
    """Answers the next of `answers` per call (ops, or an exception to raise), else no ops. Records every call."""

    def __init__(self) -> None:
        self.answers: list[tuple[Op, ...] | Exception] = []
        self.calls: list[tuple[Conversation, tuple[int, ...]]] = []

    async def decide(self, conversation: Conversation, known: Sequence[Fact], now: datetime) -> tuple[Op, ...]:
        self.calls.append((conversation, tuple(f.id for f in known)))
        answer = self.answers.pop(0) if self.answers else ()
        if isinstance(answer, Exception):
            raise answer
        return answer

    def will(self, *answers: tuple[Op, ...] | Exception) -> None:
        self.answers.extend(answers)

    def seen_turns(self, call: int = -1) -> tuple[int, ...]:
        return tuple(t.id for t in self.calls[call][0].turns)


@dataclass
class Home:
    url: str
    id: int
    alana: int
    ella: int
    talk: int
    turns: tuple[int, ...]
    writer: Scripted
    as_: list[int] = field(default_factory=list[int])

    def watermark(self, talk: int | None = None) -> object:
        return scalar(self.url, "SELECT (SELECT written_turn_id FROM memory_writes WHERE conversation_id = %s)",
                      (talk or self.talk,))

    def fact_count(self) -> int:
        return int(scalar(self.url, "SELECT count(*) FROM facts"))

    def sign_in(self, person_id: int) -> None:
        self.as_[:] = [person_id]


def build_home(url: str, writer: Scripted) -> Home:
    with psycopg.connect(url) as conn:
        hid = admin.add_household(conn, "home", "America/Denver")
        alana, ella = admin.add_person(conn, hid, "Alana"), admin.add_person(conn, hid, "Ella")
    talk = conversation(url, hid)
    for who in (alana, ella):
        scalar(url, "INSERT INTO conversation_participants VALUES (%s, %s, %s) RETURNING person_id", (talk, hid, who))
    turns = say(url, talk, "I like tea", "Noted", "I am learning piano", "Lovely", "We feed Mochi at six", speaker=alana)
    return Home(url, hid, alana, ella, talk, turns, writer, [alana])


def app_client(home: Home) -> Generator[TestClient]:
    app = create_app(Settings(database_url=home.url, build_version="t", public_url=PUBLIC))
    names = {home.alana: "Alana", home.ella: "Ella"}
    app.dependency_overrides[person_signed_in] = lambda: SignedIn(1, Person(home.as_[0], home.id, names[home.as_[0]]))
    with TestClient(app, base_url=PUBLIC, headers={"origin": PUBLIC}) as c:
        services.register(FactWriter, home.writer)
        try:
            yield c
        finally:
            services.unregister(FactWriter)


def remember(client: TestClient, conversation_id: int, turn_id: int) -> Response:
    return client.post(URL, json={"conversation_id": conversation_id, "turn_id": turn_id})
