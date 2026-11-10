"""A paste sent as an attachment on web chat: stored with the person's turn, read back on the conversation for the page
to fold, and fed to her in full with the message; held to its own size limit; refused on the kiosk, which has no
paste; and never logged."""

import pytest
from ashley.api.chat_models import ATTACHMENT_MAX_CHARS
from ashley.api.models import ChatConversation, ChatReply
from ashley.conversations.model import Attachment
from ashley.inference.reply import Reply
from fastapi.testclient import TestClient
from respond_support import Fakes, asked_last, wired as wired
from test_chat_routes import REPLY, client as client, outbox as outbox

PASTE = "Describe a theory\nof change for the group.\n" * 30


def send(client: TestClient, **body: object) -> tuple[int, dict[str, object]]:
    response = client.post("/api/chat/messages", json=body)
    return response.status_code, response.json()


def test_an_attachment_is_stored_on_the_persons_turn_and_fed_to_her_in_full(client: TestClient, wired: Fakes) -> None:
    wired.inference.script = [REPLY]
    status, body = send(client, text="here's the brief:", attachment={"title": "Brief", "text": PASTE})
    assert status == 200 and ChatReply.model_validate(body).body == "Done!"
    stored = wired.conversations.added[0]
    assert stored.text == "here's the brief:" and stored.attachment == Attachment("Brief", PASTE)
    assert PASTE in asked_last(wired.inference.prompts[0]).text


def test_the_conversation_reads_the_attachment_back_for_the_page_to_fold(client: TestClient, wired: Fakes) -> None:
    wired.inference.script = [REPLY]
    send(client, text="log:", attachment={"text": PASTE})
    got = ChatConversation.model_validate(client.get("/api/chat/conversation").json())
    person, hers = got.turns
    assert person.text == "log:" and person.attachment is not None
    assert (person.attachment.title, person.attachment.text) == (None, PASTE)
    assert hers.attachment is None


@pytest.mark.parametrize("attachment", [
    {"text": ""}, {"text": "   \n"}, {"text": "x" * (ATTACHMENT_MAX_CHARS + 1)}, {"text": "a\u0000b"},
    {"title": "t" * 200, "text": "x"}, {"title": "t", "text": "x", "extra": 1}, {}, "just a string"])
def test_an_attachment_outside_its_model_is_422_and_nothing_is_stored(client: TestClient, wired: Fakes,
                                                                      attachment: object) -> None:
    status, _ = send(client, text="hi", attachment=attachment)
    assert status == 422 and wired.conversations.calls == []


def test_an_attachment_at_the_limit_is_taken(client: TestClient, wired: Fakes) -> None:
    wired.inference.script = [REPLY]
    status, _ = send(client, text="hi", attachment={"text": "x" * ATTACHMENT_MAX_CHARS})
    assert status == 200


def test_the_message_alone_still_needs_text(client: TestClient, wired: Fakes) -> None:
    status, _ = send(client, attachment={"text": PASTE})
    assert status == 422 and wired.conversations.calls == []


def test_nothing_of_an_attachment_is_logged(client: TestClient, wired: Fakes, capsys: pytest.CaptureFixture[str]) -> None:
    wired.inference.script = [Reply(spoken="ok", text="ok")]
    capsys.readouterr()
    send(client, text="hi", attachment={"title": "zqTITLE", "text": "zqPASTED " * 20})
    out = capsys.readouterr().out
    assert "event=respond.attached" in out and f"chars={len('zqPASTED ' * 20)}" in out
    assert not [mark for mark in ("zqTITLE", "zqPASTED") if mark in out]


def test_the_schema_of_the_request_is_in_the_contract() -> None:
    from ashley.main import create_app
    from ashley.settings import Settings
    spec = create_app(Settings(database_url="", build_version="t", public_url="https://ashley.test")).openapi()
    assert "attachment" in spec["components"]["schemas"]["ChatMessage"]["properties"]
    assert "attachment" not in spec["components"]["schemas"]["KioskMessage"]["properties"]
