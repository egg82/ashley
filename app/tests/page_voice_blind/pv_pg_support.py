"""The blind page-voice tests over a real database: a turn run through `respond` over Postgres (a kill and a resume),
turns seeded through the real service, and the real app a voice route is fetched from."""

import asyncio
import hashlib
import secrets
from collections.abc import AsyncGenerator, Generator, Mapping
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from typing import Any

import psycopg
import pytest
from ashley import services
from ashley.api.chat import inbound_from as chat_inbound
from ashley.api.chat_models import ChatMessage
from ashley.api.kiosk_device import KIOSK_COOKIE
from ashley.api.person import SESSION_COOKIE
from ashley.channels.model import Device, Inbound
from ashley.conversations.conversations import Conversations
from ashley.conversations.inflight import InFlight
from ashley.conversations.model import Kind, NewTurn
from ashley.conversations.postgres import PostgresConversations
from ashley.conversations.postgres_inflight import PostgresInFlight
from ashley.db.pool import PoolDatabase
from ashley.inference.inference import Inference
from ashley.inference.model import Prompt, SystemPrompt, Task, ToolCall, ToolCalls, ToolResult, ToolSpec
from ashley.inference.reply import Reply
from ashley.inference.speech import Heard, Speech, SpeechTask, Transcript
from ashley.main import create_app
from ashley.people import admin
from ashley.people.model import Account, Household, Person
from ashley.people.people import People
from ashley.persona import persona
from ashley.senses.presence import Presence
from ashley.settings import Settings
from ashley.signin.model import SignedIn
from ashley.tools.tools import Catalogue, Tools
from contract.conversations_support import POLICY, household, person, scalar
from fastapi.testclient import TestClient
from voice_support import FakeSpeech


# --- a turn over a real database ----------------------------------------------------------------------------------

PUBLIC = "https://ashley.test"
CLAIM_S = 0.3
SWITCH = ToolSpec("switch_on", "turn something on", {"type": "object"}, reads=False)


class Hang(Exception):
    """A step scripted as `HANG` waits until its runner is killed."""


HANG = Hang()


@dataclass
class Model(Inference):
    script: list[ToolCalls | Reply | Hang] = field(default_factory=list[ToolCalls | Reply | Hang])
    asked: asyncio.Event = field(default_factory=asyncio.Event)

    async def step(self, task: Task, prompt: Prompt, output: type[Any], *,
                   conversation_id: int | None = None) -> Any:
        got = self.script.pop(0)
        if got is HANG:
            self.asked.set()
            await asyncio.Event().wait()
        assert not isinstance(got, Hang)
        return got if isinstance(got, ToolCalls) else output.model_validate(got.model_dump())

    async def generate(self, task: Task, prompt: Prompt, output: type[Any], *,
                       conversation_id: int | None = None) -> Any:
        raise AssertionError("a turn steps, it never generates")

    async def transcribe(self, task: SpeechTask, heard: Heard, *, conversation_id: int | None = None) -> Transcript:
        raise AssertionError("not used")

    async def speak(self, task: SpeechTask, text: str, *, conversation_id: int | None = None) -> Speech:
        raise AssertionError("not used")


class Switch(Tools):
    async def catalogue(self) -> Catalogue:
        return Catalogue((SWITCH,), "")

    async def call(self, call: ToolCall) -> ToolResult:
        return ToolResult(call.id, '{"on": true}')


@dataclass
class OnePerson(People):
    home: Household

    async def household(self, household_id: int) -> Household | None:
        return self.home if household_id == self.home.id else None

    async def person_for(self, system: str, external_id: str) -> Person | None:
        return None

    async def accounts(self, household_id: int, system: str) -> tuple[Account, ...]:
        return ()


class Nobody(Presence):
    async def home(self, household_id: int) -> frozenset[int] | None:
        return None


@dataclass
class World:
    url: str
    who: Person
    first: Model
    second: Model

    def inbound(self, text: str = "turn on the lamp", aloud: bool = True) -> Inbound:
        return chat_inbound(SignedIn(1, self.who), ChatMessage(text=text, said_aloud=aloud))

    def as_pod(self, model: Model) -> None:
        services.register(Inference, model)
        services.register(Tools, Switch())

    def rows(self) -> list[tuple[str, str, bool, str | None]]:
        """Every stored turn, oldest first: (author, text, follows, spoken)."""
        with psycopg.connect(self.url, autocommit=True) as conn:
            found = conn.execute("SELECT author, text, follows, spoken FROM turns ORDER BY id").fetchall()
        return [(a, t, f, s) for a, t, f, s in found]

    def hers(self) -> list[tuple[str, bool, str | None]]:
        return [(t, f, s) for a, t, f, s in self.rows() if a == "ashley"]


@pytest.fixture
def world(db_url: str, monkeypatch: pytest.MonkeyPatch) -> Generator[World]:
    def built(kind: Kind, context: persona.Context) -> Mapping[str, SystemPrompt]:
        return {"default": SystemPrompt(f"system for {kind}")}

    monkeypatch.setattr(persona, "system", built)
    house = household(db_url)
    who = Person(person(db_url, house, "Alana"), house, "Alana")
    services.register(People, OnePerson(Household(house, "home", "America/Denver", "", (who,))))
    services.register(Presence, Nobody())
    yield World(db_url, who, Model(), Model())
    for interface in (People, Presence, Inference, Tools):
        services.unregister(interface)


@asynccontextmanager
async def database(w: World) -> AsyncGenerator[PoolDatabase]:
    db = PoolDatabase(w.url, connect_timeout_s=5.0)
    await db.open()
    services.register(Conversations, PostgresConversations(db, POLICY))
    services.register(InFlight, PostgresInFlight(db, POLICY, claim_s=CLAIM_S))
    try:
        yield db
    finally:
        services.unregister(Conversations)
        services.unregister(InFlight)
        await db.close()


def kill_the_turn() -> int:
    """Cancel every task running the app's own turn code, as a dead pod does; the database's pool is left alone."""
    mine = [t for t in asyncio.all_tasks()
            if "/ashley/channels/" in str(getattr(getattr(t.get_coro(), "cr_code", None), "co_filename", ""))]
    for task in mine:
        task.cancel()
    return len(mine)


async def settled(w: World, count: int, timeout: float = 5.0) -> None:
    async with asyncio.timeout(timeout):
        while len(w.hers()) < count:
            await asyncio.sleep(0.02)


# --- turns seeded for a voice route --------------------------------------------------------------------------------

AT_REST = "a stored voice"


@dataclass
class Home:
    url: str
    house: int
    alana: Person
    sam: Person
    other_house: int
    zed: Person
    alana_token: str
    sam_token: str
    zed_token: str


def _session(conn: psycopg.Connection, who: Person) -> str:
    account = admin.add_account(conn, who.id, "authentik", f"sub-{who.id}")
    token = secrets.token_urlsafe(16)
    conn.execute("INSERT INTO sessions (token_sha256, account_id, household_id, expires_at) "
                 "VALUES (%s, %s, %s, now() + interval '1 day')",
                 (hashlib.sha256(token.encode()).digest(), account, who.household_id))
    return token


@pytest.fixture
def home(db_url: str) -> Home:
    house, other = household(db_url, "home"), household(db_url, "elsewhere")
    alana = Person(person(db_url, house, "Alana"), house, "Alana")
    sam = Person(person(db_url, house, "Sam"), house, "Sam")
    zed = Person(person(db_url, other, "Zed"), other, "Zed")
    with psycopg.connect(db_url, autocommit=True) as conn:
        tokens = [_session(conn, p) for p in (alana, sam, zed)]
    return Home(db_url, house, alana, sam, other, zed, tokens[0], tokens[1], tokens[2])


def device_in(url: str, household_id: int, token: str, name: str = "hall tablet") -> Device:
    """An unrevoked chat device whose cookie value is `token`."""
    device_id = int(scalar(url, "INSERT INTO devices (household_id, name, place, audience, medium, kind, token_sha256) "
                                "VALUES (%s, %s, 'hallway', 'present', 'text', 'chat', %s) RETURNING id",
                           (household_id, name, hashlib.sha256(token.encode()).digest())))
    return Device(device_id, household_id, name, "hallway", "present", "text", "chat")


@dataclass(frozen=True)
class Seeded:
    conversation: int
    asked: int
    turn: int


def seed(url: str, household_id: int, thread: str, speaker: int | None, *, spoken: str | None,
         text: str = "Dry all day.", follows: bool = False) -> Seeded:
    """A person turn then one of hers on `thread`, stored through the real service: (conversation, its turn, hers)."""
    made: list[Seeded] = []

    async def go() -> None:
        db = PoolDatabase(url, connect_timeout_s=5.0)
        await db.open()
        try:
            service = PostgresConversations(db, POLICY)
            talk = await service.for_thread(household_id, thread, "chat", [] if speaker is None else [speaker])
            asked = await service.add_turn(talk.id, NewTurn("person", "is it raining", speaker))
            hers_ = await service.add_turn(talk.id, NewTurn("ashley", text, answers=asked.id, follows=follows,
                                                            spoken=spoken))
            made.append(Seeded(talk.id, asked.id, hers_.id))
        finally:
            await db.close()

    asyncio.run(go())
    return made[0]


def age(url: str, conversation_id: int, seconds: float) -> None:
    """The conversation's every turn, `seconds` older by the database's clock."""
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("UPDATE turns SET at = at - make_interval(secs => %s) WHERE conversation_id = %s",
                     (seconds, conversation_id))


def teach(url: str, household_id: int, real: str, spoken: str) -> None:
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("INSERT INTO household_lexicon (household_id, real, spoken, updated_at) "
                     "VALUES (%s, %s, %s, now())", (household_id, real, spoken))


@contextmanager
def real_app(url: str, speech: FakeSpeech | None = None) -> Generator[TestClient]:
    """The app as a pod builds it over `url`, its speech scripted. No cookie is set: the test names whose."""
    app = create_app(Settings(database_url=url, build_version="t", public_url=PUBLIC))
    with TestClient(app, base_url=PUBLIC) as c:
        services.register(Inference, speech if speech is not None else FakeSpeech(audio=b"ID3-0123456789"))
        yield c


def as_person(c: TestClient, token: str) -> TestClient:
    c.cookies.set(SESSION_COOKIE, token, domain="ashley.test")
    return c


def as_device(c: TestClient, token: str) -> TestClient:
    c.cookies.set(KIOSK_COOKIE, token)
    return c


def voice_url(kind: str, turn_id: int | str) -> str:
    return f"/api/{kind}/turns/{turn_id}/voice"


