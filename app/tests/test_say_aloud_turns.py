"""Spoken in, she may answer aloud, through the real chat route with fakes behind the locator: a message tagged
`said_aloud` offers `Reply.aloud` and a typed one does not, her `spoken` is stored on her turn (a held line's too)
only when offered and chosen, the wire refuses a tag that is not a bool and a bench message with one, and the log line
names the outcome and never the words."""

import asyncio
import json
from collections.abc import Generator
from dataclasses import replace

import pytest
from ashley import services
from ashley.api.chat import inbound_from
from ashley.api.chat_models import BenchMessage, ChatMessage, KioskMessage
from ashley.api.kiosk import inbound_from as kiosk_inbound_from
from ashley.api.models import ChatConversation
from ashley.api.person import person_signed_in
from ashley.channels import aloud, to_phone
from ashley.channels.checkpoint import Checkpoint, dumps, loads
from ashley.channels.model import Device
from ashley.channels.outbox import Outbox
from ashley.channels.push.subscriptions import Subscription, Subscriptions
from ashley.channels.tool_loop import Progress
from ashley.conversations.conversations import Conversations
from ashley.conversations.inflight import InFlight
from ashley.inference.inference import Inference
from ashley.inference.reply import Reply
from ashley.main import create_app
from ashley.people.people import People
from ashley.runs.runs import NullRuns, Runs
from ashley.settings import Settings
from ashley.signin.model import SignedIn
from contract.conversations_support import events
from fastapi.testclient import TestClient
from later_support import FakeOutbox
from push_support import FakeSubscriptions, browser
from respond_support import ALANA, Fakes, wired as wired

PUBLIC = "https://ashley.test"
NOW = replace(inbound_from(SignedIn(1, ALANA), ChatMessage(text="hi")), said_aloud=True)
SAID = Reply(spoken="Done, it is on.", text="Done! It is **on**.", aloud=True)
DEVICE = Device(7, ALANA.household_id, "hall tablet", "hallway", "present", "text", "chat")


@pytest.fixture
def client(wired: Fakes) -> Generator[TestClient]:
    app = create_app(Settings(database_url="", build_version="test", public_url=PUBLIC))
    services.register(Outbox, FakeOutbox())
    services.register(People, wired.people)
    services.register(Runs, NullRuns())
    services.register(Conversations, wired.conversations)
    services.register(InFlight, InFlight.null())
    services.register(Inference, wired.inference)
    app.dependency_overrides[person_signed_in] = lambda: SignedIn(1, ALANA)
    yield TestClient(app, base_url=PUBLIC, headers={"origin": PUBLIC})
    services.unregister(Outbox)


def send(client: TestClient, **body: object) -> int:
    return client.post("/api/chat/messages", json={"text": "lights on", **body}).status_code


def hers(wired: Fakes) -> list[tuple[str, str | None]]:
    return [(t.text, t.spoken) for t in wired.conversations.added if t.author == "ashley"]


def test_a_tagged_message_offers_and_her_choice_stores_her_spoken_beside_her_text(
        client: TestClient, wired: Fakes, capsys: pytest.CaptureFixture[str]) -> None:
    wired.inference.script = [SAID]
    capsys.readouterr()
    assert send(client, said_aloud=True) == 200
    assert hers(wired) == [("Done! It is **on**.", "Done, it is on.")]
    assert [c.aloud for c in wired.contexts] == [True]
    out = capsys.readouterr().out
    assert [e["outcome"] for e in events(out, "voice.aloud")] == ["said"]
    assert "Done" not in "".join(line for line in out.splitlines() if "voice.aloud" in line)


def test_a_tagged_message_she_answers_in_text_alone_stores_no_voice_and_logs_nothing(
        client: TestClient, wired: Fakes, capsys: pytest.CaptureFixture[str]) -> None:
    wired.inference.script = [SAID.model_copy(update={"aloud": False})]
    capsys.readouterr()
    send(client, said_aloud=True)
    assert hers(wired) == [("Done! It is **on**.", None)] and [c.aloud for c in wired.contexts] == [True]
    assert events(capsys.readouterr().out, "voice.aloud") == []


@pytest.mark.parametrize("body", [{}, {"said_aloud": False}])
def test_a_typed_message_never_offers_and_her_aloud_is_ignored_and_logged(
        client: TestClient, wired: Fakes, capsys: pytest.CaptureFixture[str], body: dict[str, object]) -> None:
    wired.inference.script = [SAID]
    capsys.readouterr()
    send(client, **body)
    assert hers(wired) == [("Done! It is **on**.", None)] and [c.aloud for c in wired.contexts] == [False]
    assert [e["outcome"] for e in events(capsys.readouterr().out, "voice.aloud")] == ["not_offered"]


def test_a_held_line_stores_its_own_voice(client: TestClient, wired: Fakes) -> None:
    wired.inference.script = [Reply(answers=False, spoken="One moment.", text="One moment.", aloud=True), SAID]
    send(client, said_aloud=True)
    assert hers(wired)[0] == ("One moment.", "One moment.")
    held = [t for t in wired.conversations.added if t.author == "ashley"][0]
    assert held.follows is True


def test_the_conversation_read_flags_exactly_her_voiced_turns(client: TestClient, wired: Fakes) -> None:
    wired.inference.script = [SAID]
    send(client, said_aloud=True)
    got = ChatConversation.model_validate(client.get("/api/chat/conversation").json())
    assert [(t.author, t.voiced) for t in got.turns] == [("person", False), ("ashley", True)]


@pytest.mark.parametrize("tag", ["maybe", 5, None, [True]])
def test_a_tag_that_is_not_a_bool_is_422_and_nothing_is_stored(client: TestClient, wired: Fakes, tag: object) -> None:
    assert send(client, said_aloud=tag) == 422
    assert wired.conversations.calls == []


def test_a_bench_message_refuses_the_tag() -> None:
    with pytest.raises(ValueError):
        BenchMessage.model_validate({"text": "hi", "said_aloud": True})


def test_the_adapters_tag_the_inbound_and_leave_the_medium_text() -> None:
    kiosk = kiosk_inbound_from(DEVICE, KioskMessage(text="hi", said_aloud=True))
    assert (NOW.said_aloud, kiosk.said_aloud) == (True, True)
    assert (NOW.medium, kiosk.medium) == ("text", "text")
    assert not inbound_from(SignedIn(1, ALANA), ChatMessage(text="hi")).said_aloud
    assert not kiosk_inbound_from(DEVICE, KioskMessage(text="hi")).said_aloud


def test_the_offer_is_a_function_of_the_tag_and_text_medium_and_no_phone_comes_with_it() -> None:
    assert aloud.offered(NOW) and not aloud.offered(replace(NOW, said_aloud=False))
    assert not aloud.offered(replace(NOW, medium="spoken"))
    assert asyncio.run(to_phone.reachable(NOW, ALANA)) is None


def test_a_tagged_page_message_offers_no_phone_even_to_a_speaker_with_a_browser() -> None:
    services.register(Subscriptions, FakeSubscriptions([Subscription(1, ALANA.household_id, ALANA.id, browser())]))
    try:
        assert asyncio.run(to_phone.reachable(replace(NOW, medium="spoken"), ALANA)) == ALANA.id, "control: it can be read"
        assert asyncio.run(to_phone.reachable(NOW, ALANA)) is None
    finally:
        services.unregister(Subscriptions)


def test_a_blank_voice_she_chose_is_not_stored_and_is_logged_as_not_offered(capsys: pytest.CaptureFixture[str]) -> None:
    assert aloud.spoken(SAID.model_copy(update={"spoken": "  "}), NOW, 4) is None
    assert aloud.spoken(SAID.model_copy(update={"spoken": ""}), NOW, 4) is None
    assert aloud.spoken(SAID, NOW, 4) == SAID.spoken, "control: a real voice is kept"
    assert [e["outcome"] for e in events(capsys.readouterr().out, "voice.aloud")] == ["not_offered", "not_offered", "said"]


def test_a_checkpoint_keeps_the_tag_and_an_old_one_without_it_loads_untagged() -> None:
    saved = Checkpoint(NOW, 1, 2, ALANA.id, {}, Progress((), 0, 0))
    assert loads(dumps(saved)).inbound.said_aloud is True
    raw = json.loads(dumps(replace(saved, inbound=replace(NOW, said_aloud=False))))
    del raw["inbound"]["said_aloud"]
    assert loads(json.dumps(raw)).inbound.said_aloud is False
