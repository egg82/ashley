"""`respond` and `Reply.to_phone`: the prompt offers the speaker's phone only on a spoken channel, to a known speaker with
a subscribed browser; only then does a reply setting the field have its `text` queued for `push:<speaker id>` while
`spoken` is still delivered, and `text` is what is stored. Otherwise the field is ignored. The held path does the same
with its answer. `push.to_phone` logs the outcome, never the text."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from ashley.channels.model import Outbound
from ashley.channels.push.subscriptions import Subscription
from ashley.channels.respond import respond
from ashley.inference.reply import Reply
from ashley.persona import facts
from contract.inference_support import settle
from later_support import FakeOutbox, Logged, outbox as outbox, until
from push_support import FakeSubscriptions, browser, subscriptions as subscriptions
from respond_support import ALANA, HOME, SAM, Fakes, inbound, wired as wired

LIST = Reply(spoken="I've put three on your phone.", text="1. Ramen Nakamura\n2. Saffron Table\n3. Kettle & Pine", to_phone=True)
PLAIN = LIST.model_copy(update={"to_phone": False})


def subscribe(subs: FakeSubscriptions, person: int) -> None:
    n = len(subs.rows) + 1
    subs.rows.append(Subscription(n, HOME.id, person, browser(n)))


def stored(fakes: Fakes) -> str:
    conv = next(iter(fakes.conversations.convs.values()))
    return conv.turns[-1].text


def test_a_known_speaker_with_a_browser_on_a_spoken_channel_gets_the_text_on_their_phone(
        wired: Fakes, outbox: FakeOutbox, subscriptions: FakeSubscriptions) -> None:
    subscribe(subscriptions, ALANA.id)
    wired.inference.script = [LIST]
    out = asyncio.run(respond(inbound(medium="spoken", speaker_id=ALANA.id)))
    assert out.body == LIST.spoken and out.medium == "spoken"
    assert outbox.added == [(HOME.id, f"push:{ALANA.id}", Outbound(out.conversation_id, "text", LIST.text))]
    assert wired.contexts[0].phone is True
    assert stored(wired) == LIST.text


@pytest.mark.parametrize(("medium", "speaker", "who_has"), [
    ("text", ALANA.id, ALANA.id),       # not a spoken channel
    ("spoken", None, ALANA.id),        # unknown speaker (two people home, so presence names nobody)
    ("spoken", ALANA.id, SAM.id),      # the speaker has no browser; someone else does
    ("spoken", ALANA.id, None),        # nobody has one
])
def test_otherwise_the_phone_is_not_offered_and_the_field_is_ignored(
        wired: Fakes, outbox: FakeOutbox, subscriptions: FakeSubscriptions, medium: str, speaker: int | None,
        who_has: int | None) -> None:
    if who_has is not None:
        subscribe(subscriptions, who_has)
    wired.presence.answer = frozenset({ALANA.id, SAM.id})
    wired.inference.script = [LIST]
    out = asyncio.run(respond(inbound(medium=medium, speaker_id=speaker)))
    assert outbox.added == []
    assert wired.contexts[0].phone is False
    assert out.body == (LIST.spoken if medium == "spoken" else LIST.text)
    assert stored(wired) == out.body


def test_push_switched_off_offers_no_phone(wired: Fakes, outbox: FakeOutbox, subscriptions: FakeSubscriptions) -> None:
    subscribe(subscriptions, ALANA.id)
    subscriptions.down = True
    wired.inference.script = [LIST]
    asyncio.run(respond(inbound(medium="spoken", speaker_id=ALANA.id)))
    assert outbox.added == [] and wired.contexts[0].phone is False


def test_a_reply_not_setting_the_field_sends_nothing_though_it_could(
        wired: Fakes, outbox: FakeOutbox, subscriptions: FakeSubscriptions) -> None:
    subscribe(subscriptions, ALANA.id)
    wired.inference.script = [PLAIN]
    out = asyncio.run(respond(inbound(medium="spoken", speaker_id=ALANA.id)))
    assert outbox.added == [] and wired.contexts[0].phone is True
    assert stored(wired) == out.body == PLAIN.spoken


def test_the_held_answer_goes_to_the_phone_too(wired: Fakes, outbox: FakeOutbox,
                                                subscriptions: FakeSubscriptions) -> None:
    subscribe(subscriptions, ALANA.id)
    checking = Reply(answers=False, spoken="Let me look.", text="Let me look.")
    wired.inference.script = [checking, LIST]
    thread = "device:7"

    async def scenario() -> Outbound:
        out = await respond(replace(inbound(medium="spoken", speaker_id=ALANA.id), later=True))
        await until(lambda: len(outbox.added) == 2)
        return out

    out = settle(scenario())
    assert out.body == checking.spoken
    assert sorted(outbox.added, key=lambda added: added[1]) == [
                            (HOME.id, thread, Outbound(out.conversation_id, "spoken", LIST.spoken)),
                            (HOME.id, f"push:{ALANA.id}", Outbound(out.conversation_id, "text", LIST.text))]
    assert stored(wired) == LIST.text


def test_the_log_names_the_outcome_but_never_the_text(wired: Fakes, outbox: FakeOutbox,
                                                      subscriptions: FakeSubscriptions,
                                                      capsys: pytest.CaptureFixture[str]) -> None:
    log = Logged(capsys)
    subscribe(subscriptions, ALANA.id)
    wired.inference.script = [LIST, LIST]
    asyncio.run(respond(inbound(medium="spoken", speaker_id=ALANA.id)))
    asyncio.run(respond(inbound(medium="text", speaker_id=ALANA.id)))
    assert [e["outcome"] for e in log.events("push.to_phone")] == ["queued", "not_offered"]
    assert "Nakamura" not in log.read()


def test_the_prompt_names_the_phone_only_when_offered() -> None:
    now = datetime(2026, 10, 27, 18, 0, tzinfo=UTC)
    offered = facts.facts(now, HOME, ALANA, None, None, phone=True)
    assert facts.PHONE.format(name="Alana") in offered and "`to_phone`" in offered
    assert "to_phone" not in facts.facts(now, HOME, ALANA, None, None)
    assert "to_phone" not in facts.facts(now, HOME, None, None, None, phone=True)
