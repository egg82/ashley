"""Blind contract tests for the web chat routes (`POST /api/chat/messages`, `GET /api/chat/conversation`), written
from `api/models.py`, `openapi.json` and decisions.md alone. The fakes behind the locator are in `web_chat_support`."""

from datetime import timedelta
from typing import Any

import pytest
from ashley import logs
from ashley.api.models import ChatConversation, ChatReply
from ashley.channels.model import Inbound, Outbound
from ashley.channels.respond import RespondRefused, RespondUnavailable
from ashley.conversations.conversations import ConversationsUnavailable
from ashley.people.model import Person
from web_chat_support import (ALANA, COOKIE, ELLA, HOME, JSON, MARK, NOON, TWELVE, World, conversation, error_of, turn,
                              world as world)


# ---- POST /api/chat/messages -------------------------------------------------------------------------------------

def test_a_message_reaches_the_turn_loop_as_the_persons_own_web_chat(world: World) -> None:
    got = world.post("/api/chat/messages", ELLA, {"text": "turn on the lamp"})
    assert got.status_code == 200
    (inbound,) = world.loop.seen
    assert inbound == Inbound(household_id=HOME, thread="person:2:web", text="turn on the lamp", kind="chat",
                              medium="text", audience="owner", speaker_id=2, shared=False, place=None, channel="web",
                              later=True, later_by="turn", opens_benches=True, on_page=True,
                              remembers=inbound.remembers, heard_as=None)


@pytest.mark.parametrize("person", [ALANA, ELLA, TWELVE])
def test_the_thread_and_speaker_are_the_signed_in_person_whatever_the_body_says(world: World, person: Person) -> None:
    world.post("/api/chat/messages", person, {"text": "hello"})
    (inbound,) = world.loop.seen
    assert (inbound.thread, inbound.speaker_id, inbound.household_id) == (f"person:{person.id}:web", person.id, HOME)


def test_the_reply_is_the_turn_loops_outbound_as_a_chat_reply(world: World) -> None:
    world.loop.reply = Outbound(77, "text", "It is 21 degrees.", False)
    got = world.post("/api/chat/messages")
    assert got.status_code == 200
    assert ChatReply.model_validate(got.json()) == ChatReply(conversation_id=77, body="It is 21 degrees.", follows=False)


def test_a_reply_that_only_says_she_will_check_has_follows_true(world: World) -> None:
    world.loop.reply = Outbound(78, "text", "Let me check.", True)
    got = world.post("/api/chat/messages")
    assert ChatReply.model_validate(got.json()) == ChatReply(conversation_id=78, body="Let me check.", follows=True)


def test_the_text_reaches_the_turn_loop_unchanged(world: World) -> None:
    text = "what's the plan for Thursday?  éè \U0001f600 and 100% of it"
    world.post("/api/chat/messages", ALANA, {"text": text})
    assert world.loop.seen[0].text == text


def test_a_refused_turn_is_422_refused(world: World) -> None:
    world.loop.error = RespondRefused()
    got = world.post("/api/chat/messages")
    assert got.status_code == 422
    assert error_of(got).code == "refused"
    assert len(world.loop.seen) == 1


def test_an_unavailable_turn_is_503_unavailable(world: World) -> None:
    world.loop.error = RespondUnavailable()
    got = world.post("/api/chat/messages")
    assert got.status_code == 503
    assert error_of(got).code == "unavailable"


@pytest.mark.parametrize("body", [{}, {"text": ""}, {"text": "   \n"}, {"text": "x" * 4001}, {"text": "hi", "extra": 1},
                                  {"text": 5}])
def test_a_body_that_is_not_a_chat_request_never_reaches_the_turn_loop(world: World, body: dict[str, Any]) -> None:
    got = world.post("/api/chat/messages", ALANA, body)
    assert got.status_code == 422
    assert world.loop.seen == []


def test_four_thousand_characters_are_accepted(world: World) -> None:
    assert world.post("/api/chat/messages", ALANA, {"text": "x" * 4000}).status_code == 200


def test_no_session_is_401_and_the_turn_loop_is_not_reached(world: World) -> None:
    got = world.post("/api/chat/messages", None)
    assert got.status_code == 401
    assert error_of(got).code == "unauthorized"
    assert world.loop.seen == []


def test_an_unknown_or_expired_token_is_401(world: World) -> None:
    got = world.app.post("/api/chat/messages", json={"text": "hi"}, headers={**JSON, "cookie": f"{COOKIE}=t-999"})
    assert got.status_code == 401
    assert world.loop.seen == []


@pytest.mark.parametrize("path", ["/api/chat/messages"])
@pytest.mark.parametrize("headers", [{"origin": "https://evil.test"}, {"origin": "http://ashley.test"},
                                     {"origin": "", "sec-fetch-site": "cross-site"},
                                     {"content-type": "text/plain"},
                                     {"content-type": "application/x-www-form-urlencoded"}])
def test_a_cross_site_or_non_json_write_is_403_and_does_nothing(world: World, path: str,
                                                                headers: dict[str, str]) -> None:
    if headers.get("origin") == "":
        headers = {**headers}
        del headers["origin"]
        raw = {k: v for k, v in JSON.items() if k != "origin"}
        got = world.app.post(path, content=b'{"text": "hi"}', headers={**raw, **headers, "cookie": f"{COOKIE}=t-1"})
    else:
        got = world.app.post(path, content=b'{"text": "hi"}', headers={**JSON, **headers, "cookie": f"{COOKIE}=t-1"})
    assert got.status_code == 403
    assert error_of(got).code == "forbidden"
    assert world.loop.seen == [] and world.outbox.prefixes == []


@pytest.mark.parametrize("path", ["/api/chat/messages"])
def test_a_cross_site_write_without_a_session_is_403_not_401(world: World, path: str) -> None:
    got = world.app.post(path, json={"text": "hi"}, headers={**JSON, "origin": "https://evil.test"})
    assert got.status_code == 403


def test_the_session_store_being_down_is_503_on_every_chat_route(world: World) -> None:
    world.sessions.down = True
    for got in (world.post("/api/chat/messages"), world.get()):
        assert got.status_code == 503
        assert error_of(got).code == "unavailable"
    assert world.loop.seen == [] and world.outbox.prefixes == []


# ---- GET /api/chat/conversation ----------------------------------------------------------------------------------

def test_the_open_conversation_is_shown_with_its_turns_oldest_first(world: World) -> None:
    turns = (turn(1, "person", "hi", 0), turn(2, "ashley", "hello", 1), turn(3, "person", "lights?", 2))
    world.conversations.by_thread[(HOME, "person:1:web")] = conversation(31, turns)
    got = world.get()
    assert got.status_code == 200
    body = ChatConversation.model_validate(got.json())
    assert (body.conversation_id, body.started_at) == (31, NOON)
    assert [(t.id, t.author, t.text, t.at) for t in body.turns] == [
        (1, "person", "hi", NOON), (2, "ashley", "hello", NOON + timedelta(minutes=1)),
        (3, "person", "lights?", NOON + timedelta(minutes=2))]


def test_an_idle_conversation_is_still_shown(world: World) -> None:
    world.conversations.by_thread[(HOME, "person:1:web")] = conversation(31, (turn(1, "person", "hi"),), "idle")
    assert ChatConversation.model_validate(world.get().json()).conversation_id == 31


def test_a_closed_conversation_shows_as_none(world: World) -> None:
    world.conversations.by_thread[(HOME, "person:1:web")] = conversation(31, (turn(1, "person", "old"),), "closed")
    got = world.get()
    assert got.status_code == 200
    assert got.json() == {"thread": "person:1:web", "conversation_id": None, "started_at": None, "turns": []}


def test_before_the_first_message_everything_is_empty(world: World) -> None:
    assert world.get().json() == {"thread": "person:1:web", "conversation_id": None, "started_at": None, "turns": []}


def test_a_conversation_with_no_turns_yet_is_shown(world: World) -> None:
    world.conversations.by_thread[(HOME, "person:1:web")] = conversation(31, ())
    body = ChatConversation.model_validate(world.get().json())
    assert (body.conversation_id, body.turns) == (31, [])


def test_the_read_asks_for_exactly_the_persons_web_thread(world: World) -> None:
    world.get(ELLA)
    assert world.conversations.asked == [(HOME, "person:2:web")]


def test_one_person_never_sees_anothers_thread(world: World) -> None:
    world.conversations.by_thread[(HOME, "person:1:web")] = conversation(31, (turn(1, "person", f"alana {MARK}"),))
    world.conversations.by_thread[(HOME, "person:12:web")] = conversation(32, (turn(2, "person", "twelve"),))
    for person, expected in ((ALANA, 31), (TWELVE, 32)):
        assert ChatConversation.model_validate(world.get(person).json()).conversation_id == expected
    ella = world.get(ELLA)
    assert ella.json() == {"thread": "person:2:web", "conversation_id": None, "started_at": None, "turns": []}
    assert MARK not in ella.text


def test_the_read_changes_nothing(world: World) -> None:
    world.conversations.by_thread[(HOME, "person:1:web")] = conversation(31, (turn(1, "person", "hi"),))
    world.get()
    world.get()
    assert world.loop.seen == [] and world.outbox.prefixes == []


def test_reading_with_no_session_is_401(world: World) -> None:
    got = world.get(None)
    assert got.status_code == 401
    assert error_of(got).code == "unauthorized"
    assert world.conversations.asked == []


def test_reading_with_conversations_down_is_503(world: World) -> None:
    world.conversations.error = ConversationsUnavailable("down")
    got = world.get()
    assert got.status_code == 503
    assert error_of(got).code == "unavailable"


def test_a_message_and_its_reply_text_stay_out_of_every_log_line(world: World,
                                                                  capsys: pytest.CaptureFixture[str]) -> None:
    world.loop.reply = Outbound(5, "text", f"reply {MARK}", False)
    logs.setup()
    capsys.readouterr()
    world.post("/api/chat/messages", ALANA, {"text": f"asked {MARK}"})
    assert MARK not in capsys.readouterr().out


def test_the_declared_error_codes_are_the_ones_the_routes_answer_with() -> None:
    from contract_support import OPENAPI
    declared = {path: set(OPENAPI["paths"][path]["post" if "conversation" not in path else "get"]["responses"])
                for path in ("/api/chat/messages", "/api/chat/conversation")}
    assert declared["/api/chat/messages"] >= {"200", "401", "403", "422", "503"}
    assert declared["/api/chat/conversation"] >= {"200", "401", "503"}
