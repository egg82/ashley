"""`POST /api/messages` through the app: a signed-in device gets her reply rendered for its medium; the inbound it
builds (thread `device:<id>` or `device:<id>:<thread>`, the device's kind, place and household, shared so presence
names the speaker); 422 `refused`, 503 `unavailable`; and nothing of the body or the token in any log line."""

from typing import Any

import pytest
from ashley import logs
from ashley.channels.devices import DevicesUnavailable
from ashley.inference.inference import InferenceRefused, InferenceUnavailable
from ashley.inference.reply import Reply
from contract_support import OPENAPI
from messages_support import SPOKEN_DEVICE, TEXT_DEVICE, TEXT_TOKEN, TOKEN, FakeDevices, app, bearer
from turns_support import HOUSE, SAM, World, world as world

REPLY = Reply(spoken="It is sunny.", text="It is *sunny*.")
ERROR_CODES = {"database_unavailable", "unauthorized", "refused", "unavailable"}


def error(body: Any, code: str) -> None:
    assert set(body) == {"code", "detail"} and body["code"] == code and isinstance(body["detail"], str)


def test_the_contract_declares_the_route_and_its_statuses() -> None:
    declared = OPENAPI["paths"]["/api/messages"]["post"]["responses"]
    assert {"200", "401", "422", "503"} <= set(declared)


@pytest.mark.parametrize(("token", "device", "delivered"), [(TOKEN, SPOKEN_DEVICE, REPLY.spoken),
                                                            (TEXT_TOKEN, TEXT_DEVICE, REPLY.text)])
def test_a_device_gets_her_reply_rendered_for_its_medium(world: World, token: str, device: Any,
                                                         delivered: str) -> None:
    world.inference.then = REPLY
    with app(world, FakeDevices()) as c:
        r = c.post("/api/messages", json={"text": "is it sunny"}, headers=bearer(token))
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/json")
    body = r.json()
    assert body == {"conversation_id": body["conversation_id"], "medium": device.medium, "body": delivered}
    assert isinstance(body["conversation_id"], int)
    assert world.conversations.turns_of(body["conversation_id"])[0] == ("person", None, "is it sunny")


def test_the_inbound_is_the_devices_thread_kind_place_and_household(world: World) -> None:
    with app(world, FakeDevices()) as c:
        assert c.post("/api/messages", json={"text": "hi"}, headers=bearer(TEXT_TOKEN)).status_code == 200
    (call,) = world.conversations.thread_calls
    assert (call.household_id, call.thread, call.kind) == (HOUSE, "device:8", "chat")
    ((kind, context),) = world.persona.asked
    assert kind == "chat" and context.place == "hallway"


def test_a_named_thread_is_kept_apart(world: World) -> None:
    with app(world, FakeDevices()) as c:
        for thread in ("probe-1", None, "probe_2"):
            payload = {"text": "hi"} if thread is None else {"text": "hi", "thread": thread}
            assert c.post("/api/messages", json=payload, headers=bearer()).status_code == 200
    assert [t.thread for t in world.conversations.thread_calls] == ["device:7:probe-1", "device:7",
                                                                   "device:7:probe_2"]


def test_a_device_is_shared_so_presence_names_the_speaker(world: World) -> None:
    world.presence.answer = frozenset({SAM.id})
    with app(world, FakeDevices()) as c:
        r = c.post("/api/messages", json={"text": "hi"}, headers=bearer())
    assert world.conversations.turns_of(r.json()["conversation_id"])[0] == ("person", SAM.id, "hi")


def test_a_refusal_is_422_refused(world: World) -> None:
    world.inference.then = InferenceRefused("declined")
    with app(world, FakeDevices()) as c:
        r = c.post("/api/messages", json={"text": "hi"}, headers=bearer())
    assert r.status_code == 422
    error(r.json(), "refused")


def test_no_model_answering_is_503_unavailable(world: World) -> None:
    world.inference.then = InferenceUnavailable("none")
    with app(world, FakeDevices()) as c:
        r = c.post("/api/messages", json={"text": "hi"}, headers=bearer())
    assert r.status_code == 503
    error(r.json(), "unavailable")


@pytest.mark.parametrize("wired", [True, False])
def test_devices_unavailable_is_503_unavailable(world: World, wired: bool) -> None:
    devices = FakeDevices()
    devices.error = DevicesUnavailable("down")
    with app(world, devices if wired else None) as c:
        r = c.post("/api/messages", json={"text": "hi"}, headers=bearer())
    assert r.status_code == 503
    error(r.json(), "unavailable")
    assert world.touched() == 0


def test_nothing_of_the_body_or_the_token_reaches_a_log_line(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    mark = "zqBODY3317"
    logs.setup()
    with app(world, FakeDevices()) as c:
        capsys.readouterr()
        ok = c.post("/api/messages", json={"text": f"secret {mark}", "thread": f"t{mark}"}, headers=bearer())
        bad = c.post("/api/messages", json={"text": f"x {mark}", "extra": mark}, headers=bearer())
        unknown = c.post("/api/messages", json={"text": mark}, headers=bearer(f"{mark}-token"))
    out = capsys.readouterr().out
    assert (ok.status_code, bad.status_code, unknown.status_code) == (200, 422, 401)
    assert "/api/messages" in out, "control: the requests were logged"
    for leaked in (mark, "secret", TOKEN, "zqTOK"):
        assert leaked not in out
