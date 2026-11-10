"""Shared pieces of the reader piece's blind contract tests: reader bodies, builders for the commands, a fold of
`decide` over a list of commands, a real-database workshop with two households, her bench tools over it, and the
routes through the real app."""

import json
from collections.abc import AsyncGenerator, Iterable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from itertools import count
from typing import Any

from ashley import services
from ashley.api.person import person_signed_in
from ashley.conversations.conversations import Conversations
from ashley.conversations.inflight import InFlight
from ashley.db.pool import PoolDatabase
from ashley.inference.inference import Inference
from ashley.inference.model import ToolCall, ToolResult
from ashley.live.live import Live
from ashley.main import create_app
from ashley.people.model import Person
from ashley.settings import Settings
from ashley.signin.model import SignedIn
from ashley.tools.bench_tools import BenchTools
from ashley.tools.results import ReadPage, Results, bound
from ashley.tools.tools import Tools
from ashley.workshop import rules as workshop_rules
from ashley.workshop.commands import Add, Command, Edit, Point
from ashley.workshop.decide import EMPTY, Accepted, BenchState, Decision, Refused, decide
from ashley.workshop.model import HER, By, Owner, Piece, Text
from ashley.workshop.postgres import PostgresWorkshop
from ashley.workshop.reader import Passage, body_of
from ashley.workshop.rules import Rules
from ashley.workshop.workshop import Workshop
from contract.conversations_support import household, person
from fastapi.testclient import TestClient
from httpx2 import Response
from live_support import FakeLive
from respond_support import Fakes

RULES: Rules = workshop_rules.load()
ALANA = By(7)
SAM = By(8)
URL = "https://example.org/essay"
TITLE = "An essay"
LINES = ("The first line.", "Second line: naive café and a 😀 emoji.", "", "Fourth line with some words.")
TEXT = "\n".join(LINES)
PUBLIC = "https://ashley.test"
KIND_MAX = 200000


def body(text: str = TEXT, url: str = URL, title: str = TITLE) -> str:
    return body_of(url, title, text)


def add_reader(text: str = TEXT, by: By = ALANA, title: str = "r") -> Add:
    return Add(by, "reader", Text(title, body(text)), "medium")


def add_note(title: str = "n", text: str = "x", by: By = ALANA) -> Add:
    return Add(by, "note", Text(title, text), "small")


def edit_text(piece_id: int, base_version: int, text: str, by: By = ALANA) -> Edit:
    return Edit(by, piece_id, base_version, Text("r", body(text)))


def point(piece_id: int, base_version: int, passage: Passage | None, by: By = HER) -> Point:
    return Point(by, piece_id, base_version, passage)


def fold(commands: Iterable[Command], rules: Rules = RULES, state: BenchState = EMPTY) -> list[Decision]:
    out: list[Decision] = []
    for command in commands:
        decision = decide(state, command, rules)
        out.append(decision)
        state = decision.state
    return out


def last(*commands: Command) -> Decision:
    return fold(commands)[-1]


def end(*commands: Command) -> BenchState:
    return last(*commands).state


def reason(decision: Decision) -> str:
    assert isinstance(decision, Refused), f"expected a refusal, got {decision}"
    return decision.reason


def accepted(decision: Decision) -> Accepted:
    assert isinstance(decision, Accepted), f"expected an acceptance, got {decision}"
    return decision


def shape(piece: Piece) -> tuple[int, str, Text, int, object, int]:
    return (piece.id, piece.kind, piece.text, piece.version, piece.place, piece.changed_by)


# --- a real database ------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class World:
    """Alana and Sam share household 1; Zed is alone in household 2."""

    url: str
    alana: Owner
    sam: Owner
    zed: Owner


def world(url: str) -> World:
    h1, h2 = household(url, "one"), household(url, "two")
    return World(url, Owner(h1, person(url, h1, "Alana")), Owner(h1, person(url, h1, "Sam")),
                 Owner(h2, person(url, h2, "Zed")))


@dataclass
class Env:
    world: World
    workshop: Workshop
    live: FakeLive


@asynccontextmanager
async def env(url: str) -> AsyncGenerator[Env]:
    db = PoolDatabase(url)
    await db.open()
    live = FakeLive()
    shipped = PostgresWorkshop(db, workshop_rules.load())
    services.register(Live, live)
    services.register(Workshop, shipped)
    try:
        yield Env(world(url), shipped, live)
    finally:
        for interface in (Live, Workshop):
            services.unregister(interface)
        await db.close()


async def opened(e: Env, owner: Owner) -> int:
    return (await e.workshop.open(owner, "bench")).id


async def put(e: Env, owner: Owner, bench: int, command: Command) -> int:
    done = await e.workshop.apply(owner, bench, command)
    assert done.outcome == "accepted", done.outcome
    return done.seq


def person_by(owner: Owner) -> By:
    return By(owner.person_id)


async def reader_on(e: Env, owner: Owner, bench: int, text: str = TEXT) -> int:
    return await put(e, owner, bench, add_reader(text, person_by(owner)))


# --- her bench tools ------------------------------------------------------------------------------------------------

_ids = count(1)


def tools(owner: Owner, bench: int, results: Results | None = None) -> BenchTools:
    return BenchTools(owner.household_id, owner.person_id, bench, results=results)


async def call(t: BenchTools, results: Results | None, name: str, **arguments: object) -> ToolResult:
    tool_call = ToolCall(f"c{next(_ids)}", name, arguments)
    if results is None:
        return await t.call(tool_call)
    with bound(results):
        return await t.call(tool_call)


def js(result: ToolResult) -> Any:
    return json.loads(result.content)


def find(node: object, key: str) -> list[object]:
    """Every value under `key` in any object of a JSON document."""
    found: list[object] = []
    loose: Any = node
    if isinstance(node, dict):
        for k, v in dict[object, object](loose).items():
            if k == key:
                found.append(v)
            found.extend(find(v, key))
    elif isinstance(node, list):
        for v in list[object](loose):
            found.extend(find(v, key))
    return found


# --- routes ---------------------------------------------------------------------------------------------------------


@dataclass
class Rig:
    client: TestClient
    w: World
    live: FakeLive
    who: list[str] = field(default_factory=lambda: ["alana"])

    def as_(self, name: str) -> None:
        self.who[0] = name

    def post(self, path: str, body: object = None) -> "Reply":
        return Reply(self.client.post(path, json=body))

    def get(self, path: str) -> "Reply":
        return Reply(self.client.get(path))


@dataclass
class Reply:
    response: Response

    @property
    def status(self) -> int:
        return self.response.status_code

    @property
    def json(self) -> dict[str, Any]:
        out: dict[str, Any] = self.response.json()
        return out


def build(url: str, fakes: Fakes) -> Rig:
    w = world(url)
    app = create_app(Settings(database_url=url, build_version="t", public_url=PUBLIC))
    rig = Rig(TestClient(app, base_url=PUBLIC, headers={"origin": PUBLIC}), w, FakeLive())
    owners = {"alana": w.alana, "sam": w.sam, "zed": w.zed}

    def signed() -> SignedIn:
        o = owners[rig.who[0]]
        return SignedIn(1, Person(o.person_id, o.household_id, rig.who[0].capitalize()))

    app.dependency_overrides[person_signed_in] = signed
    services.register(Live, rig.live)
    services.register(Conversations, fakes.conversations)
    services.register(InFlight, InFlight.null())
    services.register(Inference, fakes.inference)
    services.register(Tools, fakes.tools)
    return rig


# --- reader pieces by result ----------------------------------------------------------------------------------------

PAGE_URL = "https://example.org/read-me"
LONG = "\n".join(f"line {i:05d} of the page" for i in range(2000))


def properties_of(parameters: object) -> dict[str, Any]:
    loose: Any = parameters
    found: dict[str, Any] = loose["properties"]
    return found


def rig(e: Env, bench: int, text: str = "alpha one\nbeta two three\ngamma four", title: str = "Page title",
        url: str = PAGE_URL) -> tuple[BenchTools, Results, int]:
    """Her tools for a turn that read a page: the turn's `Results` and the number of the page it kept."""
    store = Results()
    number = store.record(url)
    store.keep(number, ReadPage(title, text))
    return tools(e.world.alana, bench, store), store, number


async def added(e: Env, bench: int, t: BenchTools, store: Results, number: int) -> int:
    got = await call(t, store, "bench_add", kind="reader", title="Reading", result=number)
    assert not got.is_error, got.content
    return int(js(got)["piece_id"])


async def stored(e: Env, bench: int, piece: int) -> str:
    [found] = [p for p in (await e.workshop.read(e.world.alana, bench)).pieces if p.id == piece]
    return found.text.body
