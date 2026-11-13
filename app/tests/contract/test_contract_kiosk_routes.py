"""Blind contract tests for what the hallway tablet reads and does: its device, conversation, glance, controls and
messages (`/api/kiosk/*`), from `api/models.py`, `openapi.json` and decisions.md alone."""

from typing import Any

import pytest
from ashley.api.kiosk_glance_models import KioskGlance
from ashley.api.models import ChatConversation, ChatReply, KioskControlDone, KioskControls, KioskDevice
from ashley.channels.model import Device, Outbound
from ashley.channels.respond import RespondRefused, RespondUnavailable
from ashley.conversations.conversations import ConversationsUnavailable
from kiosk_support import DEVICE, HOME, MARK, NIGHT, Kiosk, kiosk as kiosk
from web_chat_support import NOON, conversation, error_of, turn


# ---- GET /api/kiosk/device, /conversation ------------------------------------------------------------------------

def test_the_device_is_the_one_the_token_signs_in(kiosk: Kiosk) -> None:
    other = Device(31, HOME, "porch tablet", "porch", "present", "text", "chat")
    kiosk.devices.by["other-token"] = other
    assert KioskDevice.model_validate(kiosk.get("/api/kiosk/device").json()) == KioskDevice(
        id=9, name="hallway tablet", place="hallway")
    assert KioskDevice.model_validate(kiosk.get("/api/kiosk/device", token="other-token").json()).id == 31


def test_the_conversation_is_the_open_one_on_the_devices_thread(kiosk: Kiosk) -> None:
    turns = (turn(1, "person", "hi", 0), turn(2, "ashley", "hello", 1))
    kiosk.conversations.by_thread[(HOME, "device:9")] = conversation(31, turns)
    kiosk.conversations.by_thread[(HOME, "person:1:web")] = conversation(32, (turn(3, "person", f"private {MARK}"),))
    got = kiosk.get("/api/kiosk/conversation")
    assert got.status_code == 200
    body = ChatConversation.model_validate(got.json())
    assert (body.thread, body.conversation_id, body.started_at) == ("device:9", 31, NOON)
    assert [(t.id, t.author, t.text) for t in body.turns] == [(1, "person", "hi"), (2, "ashley", "hello")]
    assert kiosk.conversations.asked == [(HOME, "device:9")] and MARK not in got.text


def test_each_device_reads_its_own_thread(kiosk: Kiosk) -> None:
    kiosk.devices.by["other-token"] = Device(31, HOME, "porch tablet", "porch", "present", "text", "chat")
    kiosk.get("/api/kiosk/conversation", token="other-token")
    assert kiosk.conversations.asked == [(HOME, "device:31")]


def test_a_closed_or_missing_conversation_shows_as_none(kiosk: Kiosk) -> None:
    empty: dict[str, Any] = {"thread": "device:9", "conversation_id": None, "started_at": None, "turns": []}
    assert kiosk.get("/api/kiosk/conversation").json() == empty
    kiosk.conversations.by_thread[(HOME, "device:9")] = conversation(31, (turn(1, "person", "old"),), "closed")
    assert kiosk.get("/api/kiosk/conversation").json() == empty


def test_reading_with_conversations_down_is_503(kiosk: Kiosk) -> None:
    kiosk.conversations.error = ConversationsUnavailable("down")
    got = kiosk.get("/api/kiosk/conversation")
    assert got.status_code == 503 and error_of(got).code == "unavailable"


# ---- GET /api/kiosk/glance ---------------------------------------------------------------------------------------

def test_the_glance_names_the_household_members_who_are_home_by_person_id(kiosk: Kiosk) -> None:
    kiosk.presence.at_home = frozenset({12, 1})
    got = kiosk.get("/api/kiosk/glance")
    assert got.status_code == 200
    assert KioskGlance.model_validate(got.json()).home == ["Alana", "Twelve"]
    assert kiosk.presence.asked == [HOME]


def test_everyone_away_is_an_empty_list_and_unknown_is_null(kiosk: Kiosk) -> None:
    kiosk.presence.at_home = frozenset()
    assert kiosk.get("/api/kiosk/glance").json()["home"] == []
    kiosk.presence.at_home = None
    assert kiosk.get("/api/kiosk/glance").json()["home"] is None


def test_a_household_that_cannot_be_read_is_an_unknown_home_not_an_error(kiosk: Kiosk) -> None:
    kiosk.presence.at_home = frozenset({1})
    kiosk.people.down = True
    got = kiosk.get("/api/kiosk/glance")
    assert got.status_code == 200 and got.json()["home"] is None


def test_someone_home_who_is_not_in_the_household_is_not_shown(kiosk: Kiosk) -> None:
    kiosk.presence.at_home = frozenset({1, 999})
    assert kiosk.get("/api/kiosk/glance").json()["home"] == ["Alana"]


def test_calendar_and_reminders_are_not_connected(kiosk: Kiosk) -> None:
    assert sorted(KioskGlance.model_validate(kiosk.get("/api/kiosk/glance").json()).not_connected) == [
        "calendar", "reminders"]


def test_the_glance_carries_nothing_of_a_persons_private_data(kiosk: Kiosk) -> None:
    kiosk.presence.at_home = frozenset({1})
    kiosk.conversations.by_thread[(HOME, "person:1:web")] = conversation(32, (turn(3, "person", f"private {MARK}"),))
    got = kiosk.get("/api/kiosk/glance")
    assert set(got.json()) == set(KioskGlance.model_fields)
    assert MARK not in got.text and kiosk.conversations.asked == []


# ---- GET /api/kiosk/controls, POST /api/kiosk/controls/{name} ----------------------------------------------------

def test_the_controls_are_the_configured_list_in_order(kiosk: Kiosk) -> None:
    got = kiosk.get("/api/kiosk/controls")
    assert got.status_code == 200
    assert [(c.name, c.label) for c in KioskControls.model_validate(got.json()).controls] == [
        ("hall-light", "Hall light"), ("lock-up", "Lock up")]
    assert "zq_hall" not in got.text and "light.turn_on" not in got.text


def test_no_controls_configured_is_an_empty_list(kiosk: Kiosk) -> None:
    kiosk.set_controls()
    assert kiosk.get("/api/kiosk/controls").json() == {"controls": []}


def test_a_control_runs_its_configured_tool_call_through_tools_not_the_model(kiosk: Kiosk) -> None:
    got = kiosk.post("/api/kiosk/controls/lock-up")
    assert got.status_code == 200
    assert KioskControlDone.model_validate(got.json()) == KioskControlDone(done=True)
    (called,) = kiosk.tools.calls
    assert (called.name, dict(called.arguments)) == ("house_do", {"action": "light.turn_off", "ids": ["light.zq_porch"]})
    assert kiosk.loop.seen == [] and MARK not in got.text


def test_each_control_runs_its_own_call_once_per_press(kiosk: Kiosk) -> None:
    kiosk.post("/api/kiosk/controls/hall-light")
    kiosk.post("/api/kiosk/controls/hall-light")
    assert [(c.name, dict(c.arguments)) for c in kiosk.tools.calls] == [
        ("house_do", {"action": "light.turn_on", "ids": ["light.zq_hall"]})] * 2


def test_a_tool_that_reports_failure_is_done_false_not_an_error(kiosk: Kiosk) -> None:
    kiosk.tools.failing.add("house_do")
    got = kiosk.post("/api/kiosk/controls/hall-light")
    assert got.status_code == 200
    assert KioskControlDone.model_validate(got.json()).done is False


@pytest.mark.parametrize("name", ["nope", "hall-ligh", "hall-light2", "a" * 40])
def test_an_unknown_control_name_is_404_and_runs_nothing(kiosk: Kiosk, name: str) -> None:
    got = kiosk.post(f"/api/kiosk/controls/{name}")
    assert got.status_code == 404 and error_of(got).code == "not_found"
    assert kiosk.tools.calls == [] and kiosk.devices.counted == []


@pytest.mark.parametrize("name", ["HALL-LIGHT", "hall_light", "HassTurnOn", "a" * 41])
def test_a_name_outside_the_control_alphabet_is_422_and_runs_nothing(kiosk: Kiosk, name: str) -> None:
    assert kiosk.post(f"/api/kiosk/controls/{name}").status_code == 422
    assert kiosk.tools.calls == []


def test_a_control_named_by_the_model_or_body_cannot_change_the_call(kiosk: Kiosk) -> None:
    kiosk.post("/api/kiosk/controls/hall-light", {"tool": "HassTurnOff", "arguments": {"name": "Oven"}})
    assert [(c.name, dict(c.arguments)) for c in kiosk.tools.calls] == [
        ("house_do", {"action": "light.turn_on", "ids": ["light.zq_hall"]})]


# ---- POST /api/kiosk/messages ------------------------------------------------------------------------------------

def test_a_message_is_a_shared_present_web_turn_on_the_devices_thread(kiosk: Kiosk) -> None:
    got = kiosk.post("/api/kiosk/messages", {"text": "turn on the lamp"})
    assert got.status_code == 200
    (seen,) = kiosk.loop.seen
    assert (seen.household_id, seen.thread, seen.text, seen.channel) == (HOME, "device:9", "turn on the lamp", "web")
    assert (seen.audience, seen.shared, seen.place, seen.speaker_id) == ("present", True, "hallway", None)
    assert (seen.later, seen.later_by, seen.device_id) == (True, "turn", 9)
    assert (seen.kind, seen.medium, seen.heard_as) == (DEVICE.kind, DEVICE.medium, None)


def test_the_message_takes_everything_from_the_device_not_the_body(kiosk: Kiosk) -> None:
    other = Device(31, 3, "den tablet", "den", "household", "text", "chat", remembers=False)
    kiosk.devices.by["den-token"] = other
    kiosk.post("/api/kiosk/messages", {"text": "hello"}, token="den-token")
    (seen,) = kiosk.loop.seen
    assert (seen.household_id, seen.thread, seen.place, seen.audience, seen.remembers) == (3, "device:31", "den",
                                                                                          "household", False)
    assert (seen.shared, seen.speaker_id, seen.later) == (True, None, True)


@pytest.mark.parametrize("extra", [{"speaker_id": 1}, {"shared": False}, {"thread": "person:1:web"},
                                   {"audience": "owner"}])
def test_a_body_naming_the_speaker_or_the_thread_is_422_and_never_reaches_the_turn_loop(kiosk: Kiosk,
                                                                                        extra: dict[str, Any]) -> None:
    got = kiosk.post("/api/kiosk/messages", {"text": "hi", **extra})
    assert got.status_code == 422 and kiosk.loop.seen == []


def test_the_text_reaches_the_turn_loop_unchanged(kiosk: Kiosk) -> None:
    text = "what's the plan for Thursday?  éè \U0001f600 and 100% of it"
    kiosk.post("/api/kiosk/messages", {"text": text})
    assert kiosk.loop.seen[0].text == text


def test_the_reply_is_the_turn_loops_answer_with_follows_false(kiosk: Kiosk) -> None:
    kiosk.loop.reply = Outbound(77, "text", "It is 21 degrees.", False)
    assert ChatReply.model_validate(kiosk.post("/api/kiosk/messages").json()) == ChatReply(
        conversation_id=77, body="It is 21 degrees.", follows=False)


def test_a_refused_turn_is_422_refused_and_an_unavailable_one_503(kiosk: Kiosk) -> None:
    kiosk.loop.error = RespondRefused()
    got = kiosk.post("/api/kiosk/messages")
    assert got.status_code == 422 and error_of(got).code == "refused"
    kiosk.loop.error = RespondUnavailable()
    got = kiosk.post("/api/kiosk/messages")
    assert got.status_code == 503 and error_of(got).code == "unavailable"


@pytest.mark.parametrize("body", [{}, {"text": ""}, {"text": "   \n"}, {"text": "x" * 4001}, {"text": 5}])
def test_a_body_that_is_not_a_chat_request_never_reaches_the_turn_loop(kiosk: Kiosk, body: dict[str, Any]) -> None:
    got = kiosk.post("/api/kiosk/messages", body)
    assert got.status_code == 422 and kiosk.loop.seen == []


def test_four_thousand_characters_are_accepted(kiosk: Kiosk) -> None:
    assert kiosk.post("/api/kiosk/messages", {"text": "x" * 4000}).status_code == 200


def test_a_scene_control_runs_house_do_with_the_scene_id(kiosk: Kiosk) -> None:
    kiosk.set_controls(NIGHT)
    assert kiosk.post("/api/kiosk/controls/night").json() == {"done": True}
    assert [(c.name, dict(c.arguments)) for c in kiosk.tools.calls] == [
        ("house_do", {"action": "scene.turn_on", "ids": ["scene.zq_night"]})]
