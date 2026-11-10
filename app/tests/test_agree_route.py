"""`POST /api/chat/agree` through the real app: the Inbound is the person's own, on their web thread, with no text and
the proposal named; each refusal is a declared 409 with its code, an unreachable system 503; a cross-site tap is
refused before anything runs; the page is told the proposal on her final answer to the turn it was held in and on no
other turn."""

from datetime import UTC, datetime

import pytest
from ashley.api import chat
from ashley.api.chat import agree_inbound
from ashley.api.models import AgreeReply, AgreeRequest, ErrorResponse
from ashley.api.person import person_signed_in
from ashley.channels.agree import Agreed, AgreeRefusal, AgreeRefused, AgreeUnavailable
from ashley.channels.model import Inbound
from ashley.conversations.model import AgreedCall, AgreedOutcome, Turn
from ashley.main import create_app
from ashley.settings import Settings
from ashley.signin.model import SignedIn
from fastapi.testclient import TestClient
from respond_support import ALANA

PUBLIC = "https://ashley.test"
THREAD = f"person:{ALANA.id}:web"
NOW = datetime(2026, 11, 7, tzinfo=UTC)


@pytest.fixture
def client() -> TestClient:
    app = create_app(Settings(database_url="", build_version="test", public_url=PUBLIC))
    app.dependency_overrides[person_signed_in] = lambda: SignedIn(1, ALANA)
    return TestClient(app, base_url=PUBLIC, headers={"origin": PUBLIC})


def test_the_tap_is_the_persons_own_turn_with_no_text_and_the_proposal_named() -> None:
    assert agree_inbound(SignedIn(1, ALANA), AgreeRequest(proposal_id=41)) == Inbound(
        household_id=ALANA.household_id, thread=THREAD, text="", kind="chat", medium="text", audience="owner",
        speaker_id=ALANA.id, shared=False, place=None, channel="web", later=True, later_by="turn", on_page=True,
        taint=None, agree=41)


def test_an_agreement_is_answered_with_what_became_of_each_call(client: TestClient,
                                                               monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[Inbound] = []

    async def done(inbound: Inbound) -> Agreed:
        seen.append(inbound)
        return Agreed(9, AgreedOutcome((AgreedCall("Switch: hall", "ran"), AgreedCall("Open: garage", "failed"))))

    monkeypatch.setattr(chat, "agree", done)
    response = client.post("/api/chat/agree", json={"proposal_id": 41})
    assert response.status_code == 200
    assert response.json() == {"conversation_id": 9, "agreed": {"interrupted": False, "carried": [
        {"summary": "Switch: hall", "status": "ran"}, {"summary": "Open: garage", "status": "failed"}]}}
    assert AgreeReply.model_validate(response.json()).agreed.carried[1].status == "failed"
    assert [i.agree for i in seen] == [41]


@pytest.mark.parametrize("reason", ["gone", "expired", "not_yours"])
def test_each_refusal_is_a_409_with_its_own_code(client: TestClient, monkeypatch: pytest.MonkeyPatch,
                                                 reason: AgreeRefusal) -> None:
    async def refuse(inbound: Inbound) -> Agreed:
        raise AgreeRefused(reason)

    monkeypatch.setattr(chat, "agree", refuse)
    response = client.post("/api/chat/agree", json={"proposal_id": 1})
    assert response.status_code == 409 and ErrorResponse.model_validate(response.json()).code == reason


def test_an_unreachable_system_is_a_503(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def down(inbound: Inbound) -> Agreed:
        raise AgreeUnavailable()

    monkeypatch.setattr(chat, "agree", down)
    response = client.post("/api/chat/agree", json={"proposal_id": 1})
    assert response.status_code == 503 and ErrorResponse.model_validate(response.json()).code == "unavailable"


@pytest.mark.parametrize("body", [{}, {"proposal_id": 0}, {"proposal_id": "x"}, {"proposal_id": 1, "text": "yes"}])
def test_a_body_outside_the_request_model_is_422(client: TestClient, monkeypatch: pytest.MonkeyPatch, body: object) -> None:
    async def never(inbound: Inbound) -> Agreed:
        raise AssertionError("asked")

    monkeypatch.setattr(chat, "agree", never)
    assert client.post("/api/chat/agree", json=body).status_code == 422


def test_a_tap_from_another_site_is_403_and_one_with_no_session_is_401(monkeypatch: pytest.MonkeyPatch) -> None:
    async def never(inbound: Inbound) -> Agreed:
        raise AssertionError("asked")

    monkeypatch.setattr(chat, "agree", never)
    app = create_app(Settings(database_url="", build_version="test", public_url=PUBLIC))
    anonymous = TestClient(app, base_url=PUBLIC)
    cross = anonymous.post("/api/chat/agree", json={"proposal_id": 1}, headers={"origin": "https://evil.test"})
    assert cross.status_code == 403 and ErrorResponse.model_validate(cross.json()).code == "forbidden"
    own = anonymous.post("/api/chat/agree", json={"proposal_id": 1}, headers={"origin": PUBLIC})
    assert own.status_code == 401 and ErrorResponse.model_validate(own.json()).code == "unauthorized"


def turn(id: int, author: str, answers: int | None = None, follows: bool = False) -> Turn:
    return Turn(id, "ashley" if author == "ashley" else "person", None, "t", NOW, follows=follows, answers=answers)


def test_the_proposal_is_on_her_final_answer_to_the_turn_it_was_held_in_and_nowhere_else() -> None:
    held = (41, 10)
    turns = [turn(10, "person"), turn(11, "ashley", 10, follows=True), turn(12, "ashley", 10), turn(13, "ashley", 9),
             turn(14, "person", 10)]
    assert [chat.agree_on(t, held) for t in turns] == [None, None, 41, None, None]
    assert [chat.agree_on(t, None) for t in turns] == [None] * 5
