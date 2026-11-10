"""Support for the blind tests of "Agree by tap" (open-work item P4; `~/scratch/ashley/readers-design/design.txt`, P4 and
the owner decisions): the real app on a real database, a signed-in person's cookie, the real proposals store and in-flight
store, a recording `Tools` behind the locator and an `Inference` that counts every call it is given.

Every guess about a name P4 adds is in the G-list below and only here, so a reconciler rewires this one file.

G1  The route is `POST /api/chat/agree` (`AGREE_PATH`), a same-site JSON write by the signed-in person, body
    `{"proposal_id": <int>}` (`agree_body`). A success is status 200 (`OK`); the response body is not read.
G2  A refusal is a 409 (`REFUSED_STATUSES`) whose JSON body (`ErrorResponse`) has the typed reason under `code`
    (`REASON_KEY`); a signed-out tap is 401 and a cross-site one 403, as every person route answers (`api.person`).
G3  The reasons (`REASONS`): another person's proposal `not_yours`, another household's `not_yours` (a household's
    proposals are not told apart from a person's), a proposal past `proposal_ttl_s` `expired`, one already carried out
    or never made `gone`. The refusal is by id and speaker alone; no model is asked.
G4  The turn is begun through `InFlight.begin`, so the checkpoint JSON it is given (`Checkpoint`, `channels.checkpoint`)
    holds the `Inbound` the route built; that `Inbound` carries the proposal id in a field named `agree`
    (`AGREE_FIELD`), has `text == ""`, `taint is None`, `author == "person"`, `audience == "owner"`, and the checkpoint's
    `tainted` is None. What is stored as the person's turn is not pinned (a turn row needs text), only that it is the
    tapping person's own and carries none of the held call's content.
G5  The held calls are carried out through the registered `Tools` (the locator's, as a household with no Home gets), by
    their stored name and arguments, in order, once. The checkpoint is saved before the first call begins, so a runner
    that dies right after `InFlight.begin` leaves the carry-out to the runner that resumes it (`channels.resume.sweep`).
G6  Logs: every agree event (taken or refused) names the proposal under the field `proposal` (`LOG_ID`) and a refusal
    carries `reason=<the typed reason>` (`LOG_REASON`; the JSON body says `code`) on a line that names that proposal; no line holds the held call's summary or
    arguments (`SUMMARY`, `ROOM`).
"""

import asyncio
import hashlib
import re
import secrets
from collections.abc import Awaitable, Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import psycopg
from ashley import services
from ashley.api.person import SESSION_COOKIE
from ashley.channels import resume
from ashley.channels.checkpoint import Checkpoint, loads
from ashley.channels.model import Inbound
from ashley.conversations.conversations import Conversations
from ashley.conversations.inflight import Claim, InFlight
from ashley.conversations.model import NewTurn
from ashley.inference.inference import Inference
from ashley.inference.model import Prompt, Task, ToolCall, ToolResult, ToolSpec
from ashley.inference.speech import Heard, Speech, SpeechTask, Transcript
from ashley.main import create_app
from ashley.people import admin
from ashley.senses.proposal_payloads import OUTSIDE, HeldCall, HeldCalls
from ashley.senses.proposals import Proposal, Proposals
from ashley.settings import Settings
from ashley.tools.outside_config import load as outside_config
from ashley.tools.tools import Catalogue, Tools
from fastapi.testclient import TestClient
from httpx2 import ASGITransport, AsyncClient, Response

PUBLIC = "https://ashley.test"
AGREE_PATH = "/api/chat/agree"
AGREE_FIELD = "agree"
REASON_KEY = "code"
LOG_ID = "proposal"
LOG_REASON = "reason"
OK = 200
UNPROCESSABLE = 422
REFUSED_STATUSES = frozenset({409})
REASONS = {"other_person": "not_yours", "other_household": "not_yours", "expired": "expired", "carried": "gone",
           "unknown": "gone"}

ROOM = "AT-PLANTED-porch-zq"
SUMMARY = "AT-SUMMARY-lamp-zq"
LAMP = ToolSpec("lamp", "turn a lamp on", {"type": "object"}, reads=False)
GARAGE = ToolSpec("garage", "move the garage door", {"type": "object"}, reads=False)
FIELDS = re.compile(r'(\w+)=("(?:[^"\\]|\\.)*"|\S*)')


async def hang(died: asyncio.Event) -> None:
    """A runner killed where it stands: it stops here for good and `tap_dying` cancels the request, as a SIGKILL ends the
    process. (A BaseException raised in the app would stop the test client's loop with it.)"""
    died.set()
    await asyncio.Event().wait()


def agree_body(proposal_id: int) -> dict[str, Any]:
    return {"proposal_id": proposal_id}


def agree_of(inbound: Inbound) -> object:
    return getattr(inbound, AGREE_FIELD, None)


def held_calls() -> tuple[HeldCall, ...]:
    return (HeldCall("lamp", {"room": ROOM}, SUMMARY),
            HeldCall("garage", {"door": 2}, "Move the garage door"))


@dataclass
class Switchboard(Tools):
    """Every call that reached it, and, with `die_in_call`, a runner that dies once the nth call has taken effect."""

    died: asyncio.Event
    ran: list[ToolCall] = field(default_factory=list[ToolCall])
    die_in_call: int | None = None

    async def catalogue(self) -> Catalogue:
        return Catalogue((LAMP, GARAGE), "")

    async def call(self, call: ToolCall) -> ToolResult:
        self.ran.append(call)
        if self.die_in_call == len(self.ran):
            self.die_in_call = None
            await hang(self.died)
        return ToolResult(call.id, "done")


@dataclass
class Counting(Inference):
    """Refuses nothing and answers nothing: every call is counted, then fails."""

    calls: int = 0

    def _asked(self) -> Exception:
        self.calls += 1
        return AssertionError("a model was asked")

    async def step(self, task: Task, prompt: Prompt, output: type[Any], *, conversation_id: int | None = None) -> Any:
        raise self._asked()

    async def generate(self, task: Task, prompt: Prompt, output: type[Any], *, conversation_id: int | None = None) -> Any:
        raise self._asked()

    async def transcribe(self, task: SpeechTask, heard: Heard, *, conversation_id: int | None = None) -> Transcript:
        raise self._asked()

    async def speak(self, task: SpeechTask, text: str, *, conversation_id: int | None = None) -> Speech:
        raise self._asked()


@dataclass
class Who:
    id: int
    token: str
    conversation: int = 0


@dataclass
class World:
    url: str
    client: TestClient
    tools: Switchboard
    model: Counting
    alana: Who
    sam: Who
    zed: Who
    died: asyncio.Event
    begun: list[str] = field(default_factory=list[str])
    die_after_begin: bool = False

    def run[T](self, work: Awaitable[T]) -> T:
        async def go() -> T:
            return await work

        portal = self.client.portal
        assert portal is not None, "the client runs the app's loop only inside its `with`"
        return portal.call(go)

    def hold(self, who: Who, calls: tuple[HeldCall, ...] | None = None) -> int:
        """A proposal of held calls `who` was asked about in an earlier turn, and its id."""
        return self.run(self._hold(who, calls or held_calls()))

    async def _hold(self, who: Who, calls: tuple[HeldCall, ...]) -> int:
        convs = services.get(Conversations)
        household = _household_of(self.url, who.id)
        conv = await convs.for_thread(household, f"person:{who.id}:web", "chat", [who.id])
        said = await convs.add_turn(conv.id, NewTurn("person", "look at the page", who.id))
        who.conversation = conv.id
        ttl = outside_config().proposal_ttl_s
        return await services.get(Proposals).propose(
            Proposal(household, who.id, conv.id, said.id, datetime.now(UTC), HeldCalls(calls)), ttl)

    def pending(self, who: Who) -> bool:
        found = self.run(services.get(Proposals).pending(who.id, who.conversation, OUTSIDE))
        return found is not None

    def tap(self, who: Who | None, proposal_id: int, headers: dict[str, str] | None = None,
            body: dict[str, Any] | None = None) -> Response:
        self.client.cookies.clear()
        if who is not None:
            self.client.cookies.set(SESSION_COOKIE, who.token, domain="ashley.test")
        sent = {"origin": PUBLIC} if headers is None else headers
        return self.client.post(AGREE_PATH, json=agree_body(proposal_id) if body is None else body, headers=sent)

    def tap_dying(self, who: Who, proposal_id: int) -> None:
        """A tap whose runner dies where `die_after_begin` or `tools.die_in_call` says; the request never answers."""
        self.run(self._dying(who, proposal_id))

    async def _dying(self, who: Who, proposal_id: int) -> None:
        async with AsyncClient(transport=ASGITransport(self.client.app), base_url=PUBLIC) as client:
            request = asyncio.create_task(client.post(
                AGREE_PATH, json=agree_body(proposal_id), headers={"origin": PUBLIC, "cookie": f"{SESSION_COOKIE}={who.token}"}))
            died = asyncio.create_task(self.died.wait())
            await asyncio.wait({request, died}, return_when=asyncio.FIRST_COMPLETED, timeout=30)
            assert died.done(), "the runner was meant to die"
            request.cancel()
            await asyncio.gather(request, return_exceptions=True)

    def settle(self, rounds: int = 3) -> None:
        """Run out every claim and let a runner finish each piece of work left, as pods do after a kill."""
        for _ in range(rounds):
            self.sql("UPDATE turn_work SET claimed_until = clock_timestamp() - interval '1 second'")
            self.run(resume.sweep())

    def sweep_together(self) -> None:
        """Two runners claiming at once."""
        self.sql("UPDATE turn_work SET claimed_until = clock_timestamp() - interval '1 second'")

        async def both() -> None:
            await asyncio.gather(resume.sweep(), resume.sweep())

        self.run(both())

    def age(self, proposal_id: int) -> None:
        self.sql("UPDATE proposals SET created_at = now() - interval '30 days' WHERE id = %s", (proposal_id,))

    def work_rows(self) -> int:
        return int(self.sql("SELECT count(*) FROM turn_work")[0][0])

    def person_turn_texts(self) -> list[str]:
        return [str(r[0]) for r in self.sql("SELECT text FROM turns WHERE author = 'person'")]

    def sql(self, query: str, params: tuple[object, ...] = ()) -> list[tuple[Any, ...]]:
        with psycopg.connect(self.url, autocommit=True) as conn:
            cur = conn.execute(query.encode(), params)
            return cur.fetchall() if cur.description else []

    def checkpoint(self) -> Checkpoint:
        assert len(self.begun) == 1, f"the agree turn was checkpointed {len(self.begun)} times"
        return loads(self.begun[0])


def _household_of(url: str, person_id: int) -> int:
    with psycopg.connect(url) as conn:
        row = conn.execute("SELECT household_id FROM people WHERE id = %s", (person_id,)).fetchone()
    assert row is not None
    return int(row[0])


def _session(conn: psycopg.Connection, person: int, household: int, tag: str) -> str:
    token = secrets.token_urlsafe(16)
    account = admin.add_account(conn, person, "oidc", f"sub-{tag}")
    conn.execute("INSERT INTO sessions (token_sha256, account_id, household_id, expires_at) "
                 "VALUES (%s, %s, %s, now() + interval '1 day')",
                 (hashlib.sha256(token.encode()).digest(), account, household))
    return token


def _people(url: str) -> tuple[Who, Who, Who]:
    with psycopg.connect(url, autocommit=True) as conn:
        home = admin.add_household(conn, "home", "America/Denver")
        away = admin.add_household(conn, "away", "America/Denver")
        ids = (admin.add_person(conn, home, "Alana"), admin.add_person(conn, home, "Sam"),
               admin.add_person(conn, away, "Zed"))
        tokens = (_session(conn, ids[0], home, "alana"), _session(conn, ids[1], home, "sam"),
                  _session(conn, ids[2], away, "zed"))
    return Who(ids[0], tokens[0]), Who(ids[1], tokens[1]), Who(ids[2], tokens[2])


@contextmanager
def world(url: str) -> Generator[World]:
    """The app as a pod builds it, over `url`, with the recording tools and the counting model behind the locator and
    `InFlight.begin` recording each checkpoint it is given."""
    alana, sam, zed = _people(url)
    app = create_app(Settings(database_url=url, build_version="t", public_url=PUBLIC))
    with TestClient(app, base_url=PUBLIC) as client:
        died = asyncio.Event()
        w = World(url, client, Switchboard(died), Counting(), alana, sam, zed, died=died)
        services.register(Tools, w.tools)
        services.register(Inference, w.model)
        _record_begin(w)
        yield w


def _record_begin(w: World) -> None:
    inner = services.get(InFlight)
    real = inner.begin

    async def begin(conversation_id: int, said_id: int, checkpoint: str) -> Claim:
        claim = await real(conversation_id, said_id, checkpoint)
        w.begun.append(checkpoint)
        if w.die_after_begin:
            w.die_after_begin = False
            await hang(w.died)
        return claim

    object.__setattr__(inner, "begin", begin)


def log_lines(text: str) -> list[dict[str, str]]:
    return [{k: v.strip('"') for k, v in FIELDS.findall(line)} for line in text.splitlines()]
