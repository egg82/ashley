"""Web chat with a paste: `POST /api/chat/messages` takes `attachment`, it is stored on the person's turn and read
back as `ChatTurn.attachment`; another person never reads it; a log line never holds it."""

import pytest
from ashley.people.model import Person
from ashley.api.chat_models import ATTACHMENT_MAX_CHARS
from ashley.api.models import ChatConversation
from bq_routes import Json, Site
from bq_support import SECRET, capture, logged, reply
from respond_support import ALANA, SAM

TYPED = "can you tidy this up for me"
PASTE = "\n".join(f"line {i} {SECRET}" for i in range(30))
ATTACHED = {"title": "Notes", "text": PASTE}


def send(site: Site, body: Json, who: Person = ALANA) -> tuple[int, Json]:
    response = site.as_(who).post("/api/chat/messages", json=body)
    return response.status_code, response.json()


def read(site: Site, who: Person = ALANA) -> ChatConversation:
    response = site.as_(who).get("/api/chat/conversation")
    assert response.status_code == 200
    return ChatConversation.model_validate(response.json())


def test_a_paste_is_stored_with_the_message_and_read_back_on_the_persons_turn(site: Site) -> None:
    site.wired.inference.script = [reply(20)]
    status, _ = send(site, {"text": TYPED, "attachment": ATTACHED})
    assert status == 200
    person, hers = read(site).turns
    assert (person.author, person.text) == ("person", TYPED)
    assert person.attachment is not None and (person.attachment.title, person.attachment.text) == ("Notes", PASTE)
    assert hers.author == "ashley" and hers.attachment is None


def test_a_message_without_a_paste_reads_back_with_the_field_null(site: Site) -> None:
    site.wired.inference.script = [reply(20)]
    assert send(site, {"text": TYPED})[0] == 200
    raw = site.as_(ALANA).get("/api/chat/conversation").json()
    assert [t["attachment"] for t in raw["turns"]] == [None, None]


def test_a_null_attachment_is_no_attachment(site: Site) -> None:
    site.wired.inference.script = [reply(20)]
    assert send(site, {"text": TYPED, "attachment": None})[0] == 200
    assert read(site).turns[0].attachment is None


def test_a_paste_without_a_title_reads_back_without_one(site: Site) -> None:
    site.wired.inference.script = [reply(20)]
    assert send(site, {"text": TYPED, "attachment": {"text": PASTE}})[0] == 200
    got = read(site).turns[0].attachment
    assert got is not None and got.title is None and got.text == PASTE


def test_she_is_given_the_whole_paste_with_the_message(site: Site) -> None:
    site.wired.inference.script = [reply(20)]
    send(site, {"text": TYPED, "attachment": ATTACHED})
    shown = repr(site.wired.inference.prompts[0].messages)
    assert PASTE.replace("\n", "\\n") in shown and TYPED in shown


def test_a_paste_of_exactly_the_maximum_is_taken_and_read_back_whole(site: Site) -> None:
    site.wired.inference.script = [reply(20)]
    text = "m" * (ATTACHMENT_MAX_CHARS - 1) + "E"
    assert send(site, {"text": TYPED, "attachment": {"text": text}})[0] == 200
    got = read(site).turns[0].attachment
    assert got is not None and got.text == text and len(got.text) == ATTACHMENT_MAX_CHARS


def test_a_paste_one_over_is_refused_and_nothing_is_stored_or_asked(site: Site) -> None:
    site.wired.inference.script = [reply(20)]
    status, _ = send(site, {"text": TYPED, "attachment": {"text": "m" * (ATTACHMENT_MAX_CHARS + 1)}})
    assert status == 422
    assert read(site).turns == [] and site.wired.inference.prompts == []


@pytest.mark.parametrize("attachment", [{"text": ""}, {"text": "  \n "}, {"text": "a\x00b"}, {}, {"title": "T"},
                                        {"text": "x", "title": "t" * 121}, {"text": "x", "extra": 1}, "just text"])
def test_a_malformed_paste_is_refused_and_nothing_happens(site: Site, attachment: object) -> None:
    site.wired.inference.script = [reply(20)]
    assert send(site, {"text": TYPED, "attachment": attachment})[0] == 422
    assert read(site).turns == [] and site.wired.inference.prompts == []


def test_a_title_of_exactly_120_is_taken(site: Site) -> None:
    site.wired.inference.script = [reply(20)]
    assert send(site, {"text": TYPED, "attachment": {"title": "t" * 120, "text": "x"}})[0] == 200
    got = read(site).turns[0].attachment
    assert got is not None and got.title == "t" * 120


def test_another_person_cannot_read_the_paste_by_any_route(site: Site) -> None:
    site.wired.inference.script = [reply(20), reply(20)]
    assert send(site, {"text": TYPED, "attachment": ATTACHED})[0] == 200
    mine = read(site)
    assert mine.conversation_id is not None
    sees = site.as_(SAM).get("/api/chat/conversation")
    assert sees.status_code == 200 and SECRET not in sees.text and read(site, SAM).turns == []
    for path in (f"/api/chat/conversations/{mine.conversation_id}", "/api/chat/conversations"):
        got = site.as_(SAM).get(path)
        assert SECRET not in got.text, path
    status, body = send(site, {"text": "line 3 violet armadillo notes tidy"}, SAM)
    assert status == 200 and SECRET not in repr(site.wired.inference.prompts[1]) and SECRET not in str(body)
    positive = site.as_(ALANA).get(f"/api/chat/conversations/{mine.conversation_id}")
    assert positive.status_code == 200 and SECRET in positive.text


def test_no_log_line_holds_the_paste_its_title_or_the_message(site: Site, caplog: pytest.LogCaptureFixture) -> None:
    capture(caplog)
    site.wired.inference.script = [reply(20)]
    body = {"text": TYPED + " " + SECRET + "-typed", "attachment": {"title": "Title " + SECRET + "-title", "text": PASTE}}
    assert send(site, body)[0] == 200
    read(site)
    assert logged(caplog, "respond.attached")
    assert SECRET not in caplog.text and TYPED not in caplog.text


def test_the_log_gives_the_length_of_the_paste(site: Site, caplog: pytest.LogCaptureFixture) -> None:
    capture(caplog)
    site.wired.inference.script = [reply(20), reply(20)]
    send(site, {"text": TYPED, "attachment": ATTACHED})
    send(site, {"text": TYPED})
    lines = logged(caplog, "respond.attached")
    assert len(lines) == 1 and str(len(PASTE)) in lines[0].values()
