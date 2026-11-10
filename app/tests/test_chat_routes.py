"""The web chat routes through the real app, with fakes behind the locator: the person's own thread and the Inbound built
for it (a held answer is stored, never queued), her reply (and `follows` on a held one), the open conversation and its
thread read back, each declared status, the same-origin write rule, and nothing of the text in the logs."""

import asyncio
from collections.abc import Generator
from dataclasses import replace

import pytest
from ashley import services
from ashley.api.chat import inbound_from
from ashley.api.models import ChatConversation, ChatConversationTurn, ChatReply, ChatRequest, ChatTurn, ErrorResponse
from ashley.api.person import person_signed_in
from ashley.channels.model import Inbound
from ashley.channels.outbox import Outbox
from ashley.conversations.conversations import Conversations, ConversationsUnavailable
from ashley.conversations.inflight import InFlight
from ashley.conversations.model import AgreedCall, AgreedOutcome, Conversation, NewTurn, Receipt, Receipts
from ashley.inference.inference import Inference, InferenceRefused, InferenceUnavailable
from ashley.inference.reply import Reply
from ashley.main import create_app
from ashley.people.people import People
from ashley.runs.runs import NullRuns, Runs
from ashley.settings import Settings
from ashley.signin.model import SignedIn
from fastapi.testclient import TestClient
from later_support import FakeOutbox
from respond_support import ALANA, EPOCH, SAM, Fakes, wired as wired

PUBLIC = "https://ashley.test"
THREAD = f"person:{ALANA.id}:web"
REPLY = Reply(spoken="Done.", text="Done!")


@pytest.fixture
def outbox() -> Generator[FakeOutbox]:
    yield FakeOutbox()
    services.unregister(Outbox)


def _app(wired: Fakes, outbox: FakeOutbox, signed_in: bool) -> TestClient:
    app = create_app(Settings(database_url="", build_version="test", public_url=PUBLIC))
    services.register(Outbox, outbox)
    services.register(People, wired.people)
    services.register(Runs, NullRuns())
    services.register(Conversations, wired.conversations)
    services.register(InFlight, InFlight.null())
    services.register(Inference, wired.inference)
    if signed_in:
        app.dependency_overrides[person_signed_in] = lambda: SignedIn(1, ALANA)
    return TestClient(app, base_url=PUBLIC, headers={"origin": PUBLIC})


@pytest.fixture
def client(wired: Fakes, outbox: FakeOutbox) -> TestClient:
    return _app(wired, outbox, signed_in=True)


def send(client: TestClient, text: str) -> tuple[int, object]:
    response = client.post("/api/chat/messages", json={"text": text})
    return response.status_code, response.json()


def test_a_message_is_the_persons_own_on_their_web_thread(client: TestClient, wired: Fakes) -> None:
    wired.inference.script = [REPLY]
    status, body = send(client, "lights on")
    assert status == 200
    assert ChatReply.model_validate(body) == ChatReply(conversation_id=1, body="Done!", follows=False)
    assert wired.conversations.calls[0] == ("for_thread", (ALANA.household_id, THREAD, "chat", (ALANA.id,)))
    assert wired.contexts[0].place is None


def test_the_inbound_is_personal_text_chat_that_takes_later_replies() -> None:
    assert inbound_from(SignedIn(1, ALANA), ChatRequest(text="hi")) == Inbound(
        household_id=ALANA.household_id, thread=THREAD, text="hi", kind="chat", medium="text", audience="owner",
        speaker_id=ALANA.id, shared=False, place=None, channel="web", remembers=True, heard_as=None, later=True,
        later_by="turn", opens_benches=True, on_page=True)


def test_a_reply_that_only_says_she_will_check_follows_and_the_answer_waits_for_later(
        client: TestClient, wired: Fakes, outbox: FakeOutbox) -> None:
    wired.inference.script = [Reply(answers=False, spoken="Let me check.", text="Let me check."), REPLY]
    status, body = send(client, "is it raining")
    assert status == 200 and ChatReply.model_validate(body).follows is True
    assert ChatReply.model_validate(body).body == "Let me check."
    assert wired.inference.prompts[0].tool_choice == "auto"


@pytest.mark.parametrize(("error", "status", "code"), [(InferenceRefused("no"), 422, "refused"),
                                                       (InferenceUnavailable("no"), 503, "unavailable")])
def test_a_reply_that_fails_is_a_declared_error(client: TestClient, wired: Fakes, error: Exception, status: int,
                                                code: str) -> None:
    wired.inference.script = [error]
    got, body = send(client, "hi")
    assert got == status and ErrorResponse.model_validate(body).code == code


@pytest.mark.parametrize("body", [{}, {"text": ""}, {"text": "   "}, {"text": "x" * 4001}, {"text": "hi", "thread": "a"}])
def test_a_body_outside_the_request_model_is_422(client: TestClient, wired: Fakes, body: object) -> None:
    response = client.post("/api/chat/messages", json=body)
    assert response.status_code == 422 and "detail" in response.json()
    assert wired.conversations.calls == []


def conversation(client: TestClient) -> ChatConversation:
    response = client.get("/api/chat/conversation")
    assert response.status_code == 200
    return ChatConversation.model_validate(response.json())


def test_the_conversation_is_empty_before_the_first_message(client: TestClient) -> None:
    assert conversation(client) == ChatConversation(thread=THREAD, conversation_id=None, started_at=None, turns=[])


def test_the_conversation_reads_back_both_sides_oldest_first(client: TestClient, wired: Fakes) -> None:
    wired.inference.script = [REPLY]
    send(client, "lights on")
    got = conversation(client)
    assert got.conversation_id == 1 and got.started_at is not None
    assert [(t.author, t.text) for t in got.turns] == [("person", "lights on"), ("ashley", "Done!")]


def test_a_turn_on_the_wire_carries_nothing_of_memory() -> None:
    assert set(ChatTurn.model_fields) == {"id", "author", "text", "at", "follows", "continued_on", "attachment"}
    assert set(ChatConversationTurn.model_fields) == {"id", "author", "text", "at", "follows", "continued_on",
                                                      "attachment", "runs", "looks", "working", "agree", "voiced", "receipts",
                                                      "agreed"}


def test_a_held_line_reads_back_as_hers_marked_follows_before_the_answer(client: TestClient, wired: Fakes) -> None:
    wired.inference.script = [Reply(answers=False, spoken="Let me check.", text="Let me check."), REPLY]
    send(client, "is it raining")
    turns = conversation(client).turns
    assert [(t.author, t.text, t.follows) for t in turns[:2]] == [("person", "is it raining", False),
                                                                  ("ashley", "Let me check.", True)]
    assert [(t.text, t.follows) for t in turns[2:]] in ([], [("Done!", False)])


def test_a_closed_conversation_reads_as_none(client: TestClient, wired: Fakes) -> None:
    wired.inference.script = [REPLY]
    send(client, "lights on")
    cid = wired.conversations.threads[THREAD]
    wired.conversations.convs[cid] = replace(wired.conversations.convs[cid], state="closed")
    assert conversation(client).turns == []


def test_another_persons_thread_is_not_read(client: TestClient, wired: Fakes) -> None:
    wired.conversations.threads[f"person:{SAM.id}:web"] = 99
    wired.conversations.convs[99] = Conversation(99, SAM.household_id, "chat", frozenset({SAM.id}), EPOCH, EPOCH,
                                                 "open", ())
    assert conversation(client).conversation_id is None


def test_the_conversation_is_503_when_unreachable(client: TestClient, wired: Fakes,
                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    async def down(household_id: int, thread: str) -> None:
        raise ConversationsUnavailable("down")

    monkeypatch.setattr(wired.conversations, "on_thread", down)
    response = client.get("/api/chat/conversation")
    assert response.status_code == 503 and ErrorResponse.model_validate(response.json()).code == "unavailable"


@pytest.mark.parametrize(("method", "path"), [("POST", "/api/chat/messages"), ("GET", "/api/chat/conversation")])
def test_no_session_is_401(wired: Fakes, outbox: FakeOutbox, method: str, path: str) -> None:
    response = _app(wired, outbox, signed_in=False).request(method, path, json={"text": "hi"} if path.endswith("messages") else None)
    assert response.status_code == 401 and ErrorResponse.model_validate(response.json()).code == "unauthorized"
    assert wired.conversations.calls == [] and outbox.prefixes == []


def test_a_write_from_another_site_is_403_before_anything_is_read(wired: Fakes, outbox: FakeOutbox) -> None:
    response = _app(wired, outbox, signed_in=False).post("/api/chat/messages", json={"text": "hi"},
                                                         headers={"origin": "https://evil.test"})
    assert response.status_code == 403 and ErrorResponse.model_validate(response.json()).code == "forbidden"
    assert wired.conversations.calls == [] and outbox.prefixes == []


def test_nothing_said_is_logged(client: TestClient, wired: Fakes, capsys: pytest.CaptureFixture[str]) -> None:
    wired.inference.script = [Reply(spoken="zqREPLY", text="zqREPLY")]
    capsys.readouterr()
    send(client, "zqSAID secret")
    conversation(client)
    out = capsys.readouterr().out
    assert "event=respond.done" in out
    assert not [mark for mark in ("zqSAID", "zqREPLY") if mark in out]


def test_a_nul_in_a_message_is_422(client: TestClient, wired: Fakes) -> None:
    response = client.post("/api/chat/messages", json={"text": "a\u0000b"})
    assert response.status_code == 422 and wired.conversations.calls == []


def test_a_nul_in_her_reply_is_removed_before_it_is_stored_or_sent(client: TestClient, wired: Fakes) -> None:
    wired.inference.script = [Reply(spoken="a\u0000b", text="c\u0000d")]
    status, body = send(client, "hi")
    assert status == 200 and ChatReply.model_validate(body).body == "cd"
    assert [t.text for t in conversation(client).turns] == ["hi", "cd"]


def test_a_turn_reads_back_with_the_receipts_stored_with_it_and_her_words_alone_in_text(client: TestClient, wired: Fakes) -> None:
    async def seed() -> None:
        talk = await wired.conversations.for_thread(ALANA.household_id, THREAD, "chat", [ALANA.id], remembered=True,
                                                    channel="web", place=None)
        said = await wired.conversations.add_turn(talk.id, NewTurn("person", "do it", ALANA.id))
        await wired.conversations.add_turn(talk.id, NewTurn("ashley", "Okay.", answers=said.id, receipts=Receipts(
            (Receipt("Sent an email", "mail_send (to: [\"a@b.test\"])", "You asked."),), (Receipt("Cancelled a reminder", "cancel_reminder (id: 4)"),), 9)))
        await wired.conversations.add_turn(talk.id, NewTurn("ashley", "Plain.", answers=said.id))

    asyncio.run(seed())
    first, last = conversation(client).turns[1:]
    assert first.text == "Okay." and first.receipts is not None and first.receipts.proposal_id == 9
    assert [(r.headline, r.detail, r.why) for r in first.receipts.ran] == [("Sent an email", 'mail_send (to: ["a@b.test"])', "You asked.")]
    assert [r.headline for r in first.receipts.held] == ["Cancelled a reminder"]
    assert first.agree is None, "no proposal is waiting for this person any more, but the snapshot stays"
    assert last.receipts is None


def test_an_agreeing_turn_reads_back_with_what_became_of_each_call_beside_it_and_no_turn_of_hers(
        client: TestClient, wired: Fakes) -> None:
    outcome = AgreedOutcome((AgreedCall("Turn on the hall lamp", "ran"), AgreedCall("Open the garage", "failed"),
                             AgreedCall("Move a message", "not_run")))

    async def seed() -> None:
        talk = await wired.conversations.for_thread(ALANA.household_id, THREAD, "chat", [ALANA.id], remembered=True,
                                                    channel="web", place=None)
        await wired.conversations.add_turn(talk.id, NewTurn("person", "do it", ALANA.id))
        tapped = await wired.conversations.add_turn(talk.id, NewTurn("person", "Agreed.", ALANA.id))
        held = wired.conversations.convs[talk.id]
        wired.conversations.convs[talk.id] = replace(held, turns=(*held.turns[:-1], replace(tapped, agreed=outcome)))

    asyncio.run(seed())
    response = client.get("/api/chat/conversation")
    first, tap = response.json()["turns"]
    assert tap["agreed"] == {"interrupted": False, "carried": [
        {"summary": "Turn on the hall lamp", "status": "ran"}, {"summary": "Open the garage", "status": "failed"},
        {"summary": "Move a message", "status": "not_run"}]}
    assert first["agreed"] is None and tap["receipts"] is None
