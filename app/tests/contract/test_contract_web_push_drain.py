"""Blind contract tests for the push singleton's drain (decisions.md, "Web push"): under the lease `push` it takes the
`push:` prefix from the outbox and sends each reply to every subscription of that person; a push service answering 404
or 410 removes that subscription, any other failure is logged with its status and the subscription kept. Logs carry ids
and counts, never the text or the endpoint. The fakes are in `web_push_support` and `later_support`."""

import pytest
from ashley.channels.model import Outbound
from ashley.channels.outbox import Later
from ashley.channels.push import config as push_config
from ashley.channels.push.later import NAME, drain
from ashley.channels.push.sender import Sent
from ashley.channels.push.subscriptions import Subscription
from contract.conversations_support import run
from later_support import FakeOutbox, Logged, Polls, drained, outbox as outbox, unavailable
from web_push_support import ALANA, ELLA, FCM, HOME, MARK, MOZILLA, FakeSender, FakeSubscriptions, browser
from web_push_support import subs as subs

POLL = 0.25


def reply(person: int, text: str = "Here is the link.", id_: int = 1, household: int = HOME,
          thread: str | None = None) -> Later:
    return Later(id_, household, thread or f"push:{person}", Outbound(40 + id_, "text", text), 900)


def drained_once(sender: FakeSender, polls: int = 1) -> Polls:
    """Run the drain for `polls` polls, as wiring builds it; the waits it made."""
    sleeper = Polls(polls)

    async def scenario() -> None:
        await drained(drain(sender, push_config.load(), POLL, sleeper))

    run(scenario())
    return sleeper


def test_the_singleton_runs_under_the_lease_named_push() -> None:
    assert NAME == "push"


def test_it_takes_exactly_the_push_prefix_and_waits_the_poll_between_polls(outbox: FakeOutbox, subs: FakeSubscriptions
                                                                            ) -> None:
    waits = drained_once(FakeSender(), polls=3)
    assert set(outbox.prefixes) == {"push:"}
    assert len(outbox.prefixes) == 3
    assert waits.waits == [POLL, POLL, POLL]


def test_a_reply_goes_to_every_browser_of_that_person_and_no_one_elses(outbox: FakeOutbox, subs: FakeSubscriptions
                                                                       ) -> None:
    mine = [browser(1), browser(2, MOZILLA)]
    subs.seed(ALANA, *mine)
    subs.seed(ELLA, browser(3))
    outbox.waiting.append(reply(ALANA.id, "Here is the link."))
    sender = FakeSender()
    drained_once(sender)
    assert sender.endpoints() == [b.endpoint for b in mine]
    assert all(n.body == "Here is the link." and n.title == "Ashley" and n.url == "/" for _, n in sender.pushed)
    assert [b for b, _ in sender.pushed] == mine


def test_a_reply_taken_is_not_taken_again(outbox: FakeOutbox, subs: FakeSubscriptions) -> None:
    subs.seed(ALANA, browser(1))
    outbox.waiting.append(reply(ALANA.id))
    sender = FakeSender()
    drained_once(sender, polls=3)
    assert len(sender.pushed) == 1


def test_person_one_is_not_person_twelve(outbox: FakeOutbox, subs: FakeSubscriptions) -> None:
    twelve = browser(12)
    subs.seed(ALANA, browser(1))
    subs.rows.append(Subscription(99, HOME, 12, twelve))
    outbox.waiting.append(reply(12, "for twelve"))
    sender = FakeSender()
    drained_once(sender)
    assert sender.endpoints() == [twelve.endpoint]


@pytest.mark.parametrize("thread", ["person:1:web", "discord:1", "push", "pushed:1", "satellite:push:1", "xpush:1"])
def test_a_thread_that_is_not_a_push_thread_is_left_for_its_channel(outbox: FakeOutbox, subs: FakeSubscriptions,
                                                                    thread: str) -> None:
    subs.seed(ALANA, browser(1))
    outbox.waiting.append(reply(ALANA.id, thread=thread))
    sender = FakeSender()
    drained_once(sender)
    assert sender.pushed == []
    assert [w.thread for w in outbox.waiting] == [thread]


def test_replies_in_one_poll_are_all_sent_oldest_first(outbox: FakeOutbox, subs: FakeSubscriptions) -> None:
    subs.seed(ALANA, browser(1))
    outbox.waiting.extend([reply(ALANA.id, "first", 1), reply(ALANA.id, "second", 2), reply(ALANA.id, "third", 3)])
    sender = FakeSender()
    drained_once(sender)
    assert [n.body for _, n in sender.pushed] == ["first", "second", "third"]


def test_a_person_with_no_browser_gets_nothing_and_the_reply_is_consumed(outbox: FakeOutbox,
                                                                          subs: FakeSubscriptions) -> None:
    subs.seed(ELLA, browser(3))
    outbox.waiting.append(reply(ALANA.id))
    sender = FakeSender()
    drained_once(sender, polls=2)
    assert sender.pushed == [] and outbox.waiting == []


def test_a_browser_of_the_same_person_id_in_another_household_gets_nothing(outbox: FakeOutbox,
                                                                           subs: FakeSubscriptions) -> None:
    subs.rows.append(Subscription(5, HOME + 1, ALANA.id, browser(1)))
    outbox.waiting.append(reply(ALANA.id, household=HOME))
    sender = FakeSender()
    drained_once(sender)
    assert sender.pushed == []


# ---- the notification ----------------------------------------------------------------------------------------------

def test_a_long_reply_is_cut_to_body_chars(outbox: FakeOutbox, subs: FakeSubscriptions) -> None:
    limit = push_config.load().body_chars
    text = "".join(f"w{n:04d} " for n in range(limit))
    subs.seed(ALANA, browser(1))
    outbox.waiting.append(reply(ALANA.id, text))
    sender = FakeSender()
    drained_once(sender)
    (_, notification), = sender.pushed
    assert 0 < len(notification.body) <= limit
    assert notification.body[:limit - 5] == text[:limit - 5]


def test_a_reply_within_body_chars_is_sent_whole(outbox: FakeOutbox, subs: FakeSubscriptions) -> None:
    limit = push_config.load().body_chars
    text = "x" * limit
    subs.seed(ALANA, browser(1))
    outbox.waiting.append(reply(ALANA.id, text))
    sender = FakeSender()
    drained_once(sender)
    assert sender.pushed[0][1].body == text


# ---- what the push service answers ---------------------------------------------------------------------------------

def test_an_accepted_push_is_recorded_as_delivered(outbox: FakeOutbox, subs: FakeSubscriptions) -> None:
    (row,) = subs.seed(ALANA, browser(1))
    outbox.waiting.append(reply(ALANA.id))
    drained_once(FakeSender())
    assert subs.delivered_ids == [row.id] and subs.gone_ids == []


@pytest.mark.parametrize("status", [404, 410])
def test_a_push_service_that_says_gone_loses_that_subscription_only(outbox: FakeOutbox, subs: FakeSubscriptions,
                                                                    status: int) -> None:
    dead, alive = subs.seed(ALANA, browser(1), browser(2))
    outbox.waiting.append(reply(ALANA.id))
    sender = FakeSender({dead.browser.endpoint: Sent("gone", status)})
    drained_once(sender)
    assert subs.gone_ids == [dead.id]
    assert subs.endpoints(ALANA.id) == [alive.browser.endpoint]
    assert subs.delivered_ids == [alive.id]
    assert sender.endpoints() == [dead.browser.endpoint, alive.browser.endpoint]


@pytest.mark.parametrize("status", [None, 400, 401, 403, 413, 429, 500, 502, 503])
def test_any_other_failure_keeps_the_subscription_and_logs_the_status(outbox: FakeOutbox, subs: FakeSubscriptions,
                                                                      capsys: pytest.CaptureFixture[str],
                                                                      status: int | None) -> None:
    flaky, fine = subs.seed(ALANA, browser(1), browser(2))
    outbox.waiting.append(reply(ALANA.id, "the text " + MARK))
    logged = Logged(capsys)
    sender = FakeSender({flaky.browser.endpoint: Sent("failed", status)})
    drained_once(sender)
    assert subs.gone_ids == [] and subs.delivered_ids == [fine.id]
    assert subs.endpoints(ALANA.id) == [flaky.browser.endpoint, fine.browser.endpoint]
    if status is not None:
        assert str(status) in logged.read()


def test_a_failed_push_does_not_stop_the_rest_of_the_person_nor_the_next_reply(outbox: FakeOutbox,
                                                                                subs: FakeSubscriptions) -> None:
    first, second = subs.seed(ALANA, browser(1), browser(2))
    outbox.waiting.extend([reply(ALANA.id, "one", 1), reply(ALANA.id, "two", 2)])
    sender = FakeSender({first.browser.endpoint: Sent("failed", 500)})
    drained_once(sender)
    assert [(b.endpoint, n.body) for b, n in sender.pushed] == [
        (first.browser.endpoint, "one"), (second.browser.endpoint, "one"),
        (first.browser.endpoint, "two"), (second.browser.endpoint, "two")]


# ---- faults --------------------------------------------------------------------------------------------------------

def test_an_outbox_that_cannot_be_reached_is_polled_again(outbox: FakeOutbox, subs: FakeSubscriptions) -> None:
    subs.seed(ALANA, browser(1))
    outbox.waiting.append(reply(ALANA.id))
    outbox.take_errors = [unavailable()]
    sender = FakeSender()
    drained_once(sender, polls=2)
    assert len(sender.pushed) == 1


def test_subscriptions_that_cannot_be_reached_do_not_end_the_drain(outbox: FakeOutbox, subs: FakeSubscriptions) -> None:
    subs.seed(ALANA, browser(1))
    outbox.waiting.append(reply(ALANA.id, "lost?", 1))
    subs.down = True
    sender = FakeSender()
    waits = drained_once(sender, polls=2)
    assert len(waits.waits) == 2
    subs.down = False
    outbox.waiting.append(reply(ALANA.id, "later", 2))
    drained_once(sender)
    assert "later" in [n.body for _, n in sender.pushed]


# ---- logs ----------------------------------------------------------------------------------------------------------

def test_logs_carry_no_text_no_endpoint_and_no_keys(outbox: FakeOutbox, subs: FakeSubscriptions,
                                                    capsys: pytest.CaptureFixture[str]) -> None:
    logged = Logged(capsys)
    b = [browser(1), browser(2), browser(3), browser(4)]
    subs.seed(ALANA, *b)
    outbox.waiting.append(reply(ALANA.id, "secret words " + MARK))
    sender = FakeSender({b[1].endpoint: Sent("gone", 410), b[2].endpoint: Sent("failed", 500),
                         b[3].endpoint: Sent("failed", None)})
    drained_once(sender)
    out = logged.read()
    assert out, "the drain logged nothing for a gone browser and two failures"
    for secret in (MARK, "secret words", FCM, "fcm.googleapis.com", *[x for k in b for x in (k.endpoint, k.p256dh, k.auth)]):
        assert secret not in out
