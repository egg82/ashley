"""Contract 8 (and the adapters' half of 2 and 7), blind: the tag on the wire. `said_aloud` is a bool on the web chat's
and the kiosk's message body and on nothing else; the adapters copy it to the `Inbound` and never infer it."""

from collections.abc import Generator

import pytest
from ashley import services
from ashley.api.chat_models import BenchMessage, ChatMessage, ChatRequest, KioskMessage
from ashley.channels.model import Inbound, Outbound
from ashley.channels.devices import Devices
from fastapi.testclient import TestClient
from pydantic import ValidationError
from pv_support import FakeDevices, kiosk_client
from respond_support import Fakes, wired as wired
from test_chat_routes import client as client, outbox as outbox

JUNK: list[object] = ["maybe", 2, [], {}, None, "nope", 0.5]


@pytest.fixture
def seen(monkeypatch: pytest.MonkeyPatch) -> list[Inbound]:
    got: list[Inbound] = []

    async def respond(inbound: Inbound) -> Outbound:
        got.append(inbound)
        return Outbound(1, "text", "ok")

    monkeypatch.setattr("ashley.api.chat.respond", respond)
    return got


@pytest.fixture
def kiosk(wired: Fakes) -> Generator[TestClient]:
    yield kiosk_client(wired, FakeDevices())
    services.unregister(Devices)


def test_c08_the_tag_defaults_off_on_the_two_models_that_carry_it() -> None:
    assert ChatMessage(text="hi").said_aloud is False
    assert KioskMessage(text="hi").said_aloud is False
    assert ChatMessage(text="hi", said_aloud=True).said_aloud is True
    assert KioskMessage(text="hi", said_aloud=True).said_aloud is True


def test_c08_the_kiosk_model_is_a_chat_request_and_the_chat_message_still_takes_its_paste() -> None:
    assert issubclass(KioskMessage, ChatRequest) and issubclass(ChatMessage, ChatRequest)
    assert ChatMessage.model_validate({"text": "hi", "attachment": {"text": "pasted"}}).attachment is not None


def test_c08_chat_request_and_bench_message_refuse_the_field() -> None:
    assert "said_aloud" not in ChatRequest.model_fields and "said_aloud" not in BenchMessage.model_fields
    for model in (ChatRequest, BenchMessage):
        with pytest.raises(ValidationError):
            model.model_validate({"text": "hi", "said_aloud": True})


@pytest.mark.parametrize("junk", JUNK)
def test_c08_a_chat_message_with_said_aloud_that_is_not_a_bool_is_422(client: TestClient, wired: Fakes,
                                                                      junk: object) -> None:
    response = client.post("/api/chat/messages", json={"text": "hi", "said_aloud": junk})
    assert response.status_code == 422 and "detail" in response.json()
    assert wired.conversations.calls == []


@pytest.mark.parametrize("junk", JUNK)
def test_c08_a_kiosk_message_with_said_aloud_that_is_not_a_bool_is_422(kiosk: TestClient, wired: Fakes,
                                                                       junk: object) -> None:
    response = kiosk.post("/api/kiosk/messages", json={"text": "hi", "said_aloud": junk})
    assert response.status_code == 422
    assert wired.conversations.calls == []


def test_c08_a_bench_message_with_said_aloud_is_422_and_without_it_is_not(client: TestClient) -> None:
    refused = client.post("/api/benches/1/messages", json={"text": "hi", "said_aloud": True})
    assert refused.status_code == 422
    control = client.post("/api/benches/1/messages", json={"text": "hi"})
    assert control.status_code != 422, "control: the same body without the field passes validation"


def test_c02_a_tagged_web_message_reaches_the_turn_loop_tagged_and_in_text(client: TestClient,
                                                                             seen: list[Inbound]) -> None:
    assert client.post("/api/chat/messages", json={"text": "hi", "said_aloud": True}).status_code == 200
    assert client.post("/api/chat/messages", json={"text": "hi", "said_aloud": False}).status_code == 200
    assert client.post("/api/chat/messages", json={"text": "hi"}).status_code == 200
    assert [getattr(i, "said_aloud") for i in seen] == [True, False, False]
    assert {i.medium for i in seen} == {"text"}


def test_c02_a_tagged_kiosk_message_reaches_the_turn_loop_tagged_and_in_text(kiosk: TestClient,
                                                                               seen: list[Inbound]) -> None:
    assert kiosk.post("/api/kiosk/messages", json={"text": "hi", "said_aloud": True}).status_code == 200
    assert kiosk.post("/api/kiosk/messages", json={"text": "hi"}).status_code == 200
    assert [getattr(i, "said_aloud") for i in seen] == [True, False]
    assert {i.medium for i in seen} == {"text"}
    assert all(i.device_id == 7 for i in seen)


def test_c02_the_tag_is_not_inferred_from_the_text(client: TestClient, seen: list[Inbound]) -> None:
    client.post("/api/chat/messages", json={"text": "I said this aloud, set aloud please"})
    assert [getattr(i, "said_aloud") for i in seen] == [False]
