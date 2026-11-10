"""Support for the blind wire tests: the real app with a conversation of fixed turns behind the locator, the pending
proposal store in memory, and a signed-in Alana; a reply's wire read as JSON (G5 of `receipts_blind_support`)."""

from collections.abc import Generator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from ashley import services
from ashley.api import messages
from ashley.api.person import person_signed_in
from ashley.channels.model import Device
from ashley.conversations.conversations import Conversations
from ashley.conversations.inflight import InFlight
from ashley.conversations.model import Carried, Conversation, Cursor, NewTurn, Page, Receipt, Receipts, Turn
from ashley.main import create_app
from ashley.people.people import People
from ashley.runs.runs import NullRuns, Runs
from ashley.senses.proposal_payloads import OUTSIDE, HeldCall, HeldCalls
from ashley.senses.proposals import Proposal, Proposals
from ashley.settings import Settings
from ashley.signin.model import SignedIn
from fastapi.testclient import TestClient
from receipts_blind_unit_support import Numbered
from respond_support import ALANA, FakePeople

PUBLIC = "https://ashley.test"
DEVICE = Device(7, ALANA.household_id, "kitchen satellite", "kitchen", "present", "spoken", "command")
AT = datetime(2026, 11, 8, 9, 0, tzinfo=UTC)
OK_TEXT = "Okay, that is on its way."
RECEIPTS = Receipts((Receipt("Did the first thing", "first (a: 1)", "RB-why-1"),),
                    (Receipt("Held the second thing", "second (b: 2)", None),), 7)
DONE_ONLY = Receipts((Receipt("Did the first thing", None, None),), (), None)


def turn(n: int, author: str, text: str, receipts: Receipts | None = None, answers: int | None = None) -> Turn:
    return Turn(n, "ashley" if author == "ashley" else "person", None if author == "ashley" else ALANA.id, text,
                AT + timedelta(minutes=n), answers=answers, receipts=receipts)


def conversation(*turns: Turn) -> Conversation:
    return Conversation(5, ALANA.household_id, "chat", frozenset({ALANA.id}), AT, AT, "open", turns)


@dataclass
class Fixed(Conversations):
    found: Conversation

    async def get(self, conversation_id: int) -> Conversation | None:
        return self.found if conversation_id == self.found.id else None

    async def on_thread(self, household_id: int, thread: str) -> Conversation | None:
        return self.found

    async def answer_to(self, household_id: int, source: str) -> Turn | None:
        raise AssertionError("not used")

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


class Site:
    """A client of the app with `found` as the open conversation and `proposals` as the pending ones."""

    def __init__(self, client: TestClient, proposals: Numbered) -> None:
        self.client = client
        self.proposals = proposals

    def turns(self) -> list[dict[str, Any]]:
        body = self.client.get("/api/chat/conversation").json()
        return list(body["turns"])

    async def take(self, turn_id: int) -> object:
        return await self.proposals.take(ALANA.id, 5, OUTSIDE, turn_id, 60)

    async def hold(self, turn_id: int, calls: tuple[HeldCall, ...] = (HeldCall("second", {"b": 2}, "second (b: 2)"),)) -> int:
        return await self.proposals.propose(
            Proposal(ALANA.household_id, ALANA.id, 5, turn_id, datetime.now(UTC), HeldCalls(calls)), 60)


def open_app(found: Conversation) -> Generator[Site]:
    app = create_app(Settings(database_url="", build_version="t", public_url=PUBLIC))
    proposals = Numbered()
    services.register(Conversations, Fixed(found))
    services.register(Runs, NullRuns())
    services.register(InFlight, InFlight.null())
    services.register(People, FakePeople())
    services.register(Proposals, proposals)
    app.dependency_overrides[person_signed_in] = lambda: SignedIn(1, ALANA)
    yield Site(TestClient(app, base_url=PUBLIC, headers={"origin": PUBLIC}), proposals)


def device_client() -> TestClient:
    """The app with a signed-in satellite, for `POST /api/messages`."""
    app = create_app(Settings(database_url="", build_version="t", public_url=PUBLIC))
    app.dependency_overrides[messages.signed_in] = lambda: DEVICE
    return TestClient(app, base_url=PUBLIC)


@pytest.fixture
def page() -> Generator[Site]:
    yield from open_app(conversation(turn(1, "person", "turn it on"), turn(2, "ashley", OK_TEXT, RECEIPTS, answers=1),
                                     turn(3, "person", "thanks"), turn(4, "ashley", "Any time.", None, answers=3)))
