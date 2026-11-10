"""Blind contract tests for sending a reply to a phone (decisions.md, "Web push"; `channels/to_phone.py`): `Reply.to_phone`
is honoured only on a spoken channel whose known speaker has at least one subscription; then the reply's `text` is queued
to `push:<speaker id>`; otherwise it is ignored. One person's phone never gets another's reply. Logs carry ids and
counts, never the text or the endpoint. The last test runs the queue through the drain."""

import asyncio

import pytest
from ashley.channels.model import Inbound, Outbound
from ashley.channels.outbox import Later
from ashley.channels.push import config as push_config
from ashley.channels.push.later import drain
from ashley.channels.outbox import Pushed
from ashley.channels.to_phone import copy, reachable
from ashley.inference.reply import Reply
from ashley.people.model import Person
from contract.conversations_support import run
from later_support import FakeOutbox, Logged, Polls, drained, outbox as outbox
from web_push_support import ALANA, ELLA, HOME, MARK, FakeSender, FakeSubscriptions, browser, subs as subs

CONVERSATION = 61


def inbound(medium: str = "spoken", speaker: int | None = 1) -> Inbound:
    assert medium in ("spoken", "text")
    return Inbound(household_id=HOME, thread="device:kitchen", text="what is the link", kind="command",
                   medium="spoken" if medium == "spoken" else "text", audience="present", speaker_id=speaker,
                   shared=True, place="kitchen", channel="voice")


def a_reply(to_phone: bool = True) -> Reply:
    return Reply(answers=True, spoken="I have put the link on your phone.", text="https://example.test/page " + MARK,
                 to_phone=to_phone)


def offered(speaker: Person | None, inb: Inbound | None = None) -> int | None:
    async def scenario() -> int | None:
        return await reachable(inb or inbound(), speaker)

    return asyncio.run(scenario())


def queued(reply: Reply, phone: int | None) -> Pushed | None:
    return copy(reply, phone, HOME, CONVERSATION)


# ---- who is offered a phone ----------------------------------------------------------------------------------------

def test_a_known_speaker_with_a_subscription_on_a_spoken_channel_is_offered_their_phone(subs: FakeSubscriptions) -> None:
    subs.seed(ALANA, browser(1))
    assert offered(ALANA) == ALANA.id


def test_one_subscription_is_enough_and_more_change_nothing(subs: FakeSubscriptions) -> None:
    subs.seed(ELLA, browser(1), browser(2), browser(3))
    assert offered(ELLA, inbound(speaker=ELLA.id)) == ELLA.id


def test_a_written_channel_is_never_offered_a_phone(subs: FakeSubscriptions) -> None:
    subs.seed(ALANA, browser(1))
    assert offered(ALANA, inbound("text")) is None


def test_no_known_speaker_is_offered_no_phone_whoever_is_subscribed(subs: FakeSubscriptions) -> None:
    subs.seed(ALANA, browser(1))
    subs.seed(ELLA, browser(2))
    assert offered(None, inbound(speaker=None)) is None


def test_a_speaker_with_no_subscription_is_offered_none_though_the_household_has_some(subs: FakeSubscriptions) -> None:
    subs.seed(ELLA, browser(2))
    assert offered(ALANA) is None


def test_subscriptions_that_cannot_be_read_offer_no_phone(subs: FakeSubscriptions) -> None:
    subs.seed(ALANA, browser(1))
    subs.down = True
    assert offered(ALANA) is None


def test_push_that_is_not_wired_offers_no_phone() -> None:
    assert offered(ALANA) is None


# ---- sending -------------------------------------------------------------------------------------------------------

def test_the_text_is_queued_to_the_speakers_push_thread() -> None:
    reply = a_reply()
    assert queued(reply, ALANA.id) == Pushed(HOME, f"push:{ALANA.id}", Outbound(CONVERSATION, "text", reply.text))


def test_it_is_the_text_that_is_queued_not_what_is_said_aloud() -> None:
    made = queued(a_reply(), ELLA.id)
    assert made is not None
    assert made.thread == "push:2" and made.outbound.body != a_reply().spoken and made.outbound.medium == "text"


def test_a_reply_that_does_not_ask_for_the_phone_queues_nothing() -> None:
    assert queued(a_reply(to_phone=False), ALANA.id) is None


def test_a_reply_asking_for_a_phone_that_was_not_offered_queues_nothing() -> None:
    assert queued(a_reply(), None) is None


# ---- logs ----------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("phone", [ALANA.id, None])
def test_logs_carry_ids_and_never_the_text(outbox: FakeOutbox, subs: FakeSubscriptions, phone: int | None,
                                           capsys: pytest.CaptureFixture[str]) -> None:
    logged = Logged(capsys)
    b = browser(1)
    subs.seed(ALANA, b)
    offered(ALANA)
    queued(a_reply(), phone)
    out = logged.read()
    assert out
    for secret in (MARK, "example.test", "put the link", b.endpoint, b.p256dh, b.auth):
        assert secret not in out


# ---- end to end through the drain ------------------------------------------------------------------------------------

def test_one_persons_phone_never_gets_anothers_reply(outbox: FakeOutbox, subs: FakeSubscriptions) -> None:
    alana, ella = browser(1), browser(2)
    subs.seed(ALANA, alana)
    subs.seed(ELLA, ella)
    assert offered(ELLA, inbound(speaker=ELLA.id)) == ELLA.id
    made = queued(a_reply(), ELLA.id)
    assert made is not None
    outbox.waiting.append(Later(1, made.household_id, made.thread, made.outbound, 100))
    sender = FakeSender()

    async def scenario() -> None:
        await drained(drain(sender, push_config.load(), 0.25, Polls(2)))

    run(scenario())
    assert sender.endpoints() == [ella.endpoint]
    assert sender.pushed[0][1].body == made.outbound.body
