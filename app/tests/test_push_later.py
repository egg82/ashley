"""`push.later`: a reply queued for `push:<person id>` is sent to every browser of that person in that household, titled
`Ashley`, its text cut to `body_chars`, a click opening `/`; a browser whose push service answers 404 or 410 is forgotten,
any other failure keeps it; each accepted send is recorded. `drain` takes only `push:` threads, every poll. Logs carry
counts and ids, never the text."""

import pytest
from ashley.channels.outbox import Later
from ashley.channels.push import config as push_config
from ashley.channels.push.later import cut, drain, push, thread
from ashley.channels.push.sender import Notification, Sent
from ashley.channels.push.subscriptions import Subscription
from contract.conversations_support import run
from later_support import FakeOutbox, Logged, Polls, drained, outbox as outbox, waiting
from push_support import FakeSender, FakeSubscriptions, browser, subscriptions as subscriptions

CONFIG = push_config.load()
SECRET = "zqLEAK9033 the door code is 4471"
ALANA, SAM, HOUSE = 1, 2, 1


def subscribed(subs: FakeSubscriptions, person: int, n: int, household: int = HOUSE) -> Subscription:
    made = Subscription(n, household, person, browser(n))
    subs.rows.append(made)
    return made


def queued(person: int = ALANA, body: str = "It's on your phone.") -> Later:
    return waiting(thread(person), body, medium="text", age_ms=300)


def pushed(sender: FakeSender, later: Later) -> None:
    async def scenario() -> None:
        await push(sender, CONFIG, later)

    run(scenario())


def test_a_reply_goes_to_every_browser_of_that_person_only(subscriptions: FakeSubscriptions) -> None:
    subscribed(subscriptions, ALANA, 1)
    subscribed(subscriptions, ALANA, 2)
    subscribed(subscriptions, SAM, 3)
    subscribed(subscriptions, ALANA, 4, household=99)
    sender = FakeSender()
    pushed(sender, queued(ALANA, "Three ramen places near you."))
    assert [b.endpoint for b, _ in sender.sends] == [browser(1).endpoint, browser(2).endpoint]
    assert {n for _, n in sender.sends} == {Notification("Ashley", "Three ramen places near you.", "/")}
    assert subscriptions.delivered_ids == [1, 2]


@pytest.mark.parametrize("status", [404, 410])
def test_a_browser_its_service_says_is_gone_is_forgotten(subscriptions: FakeSubscriptions, status: int) -> None:
    subscribed(subscriptions, ALANA, 1)
    subscribed(subscriptions, ALANA, 2)
    sender = FakeSender({browser(1).endpoint: Sent("gone", status)})
    pushed(sender, queued())
    assert [r.id for r in subscriptions.rows] == [2]
    assert subscriptions.delivered_ids == [2]


@pytest.mark.parametrize("sent", [Sent("failed", 500), Sent("failed", 429), Sent("failed", None)])
def test_any_other_failure_keeps_the_browser_and_logs_the_status(subscriptions: FakeSubscriptions, sent: Sent,
                                                                 capsys: pytest.CaptureFixture[str]) -> None:
    log = Logged(capsys)
    subscribed(subscriptions, ALANA, 1)
    pushed(FakeSender({browser(1).endpoint: sent}), queued())
    assert [r.id for r in subscriptions.rows] == [1] and subscriptions.delivered_ids == []
    (line,) = log.events("push.send_failed")
    assert line["subscription"] == "1" and line["status"] == str(sent.status or "none")


def test_a_long_reply_is_cut_to_body_chars_on_a_word() -> None:
    text = " ".join(["word"] * 300)
    got = cut(text, 40)
    assert len(got) <= 40 and got.endswith("…") and got[:-1] == " ".join(["word"] * 7)
    assert cut("short enough", 40) == "short enough"
    assert cut("x" * 50, 40) == "x" * 39 + "…"


def test_the_log_carries_counts_and_ids_but_no_words_endpoints_or_keys(
        subscriptions: FakeSubscriptions, capsys: pytest.CaptureFixture[str]) -> None:
    log = Logged(capsys)
    subscribed(subscriptions, ALANA, 1)
    subscribed(subscriptions, ALANA, 2)
    pushed(FakeSender({browser(2).endpoint: Sent("gone", 410)}), waiting(thread(ALANA), SECRET, conversation_id=88,
                                                                          medium="text", age_ms=300))
    (line,) = log.events("push.later")
    assert (line["person"], line["conversation"], line["sent"], line["gone"], line["failed"], line["age_ms"]) == (
        "1", "88", "1", "1", "0", "300")
    text = log.read()
    assert "zqLEAK9033" not in text and "fcm.googleapis.com" not in text and browser(1).auth not in text


def test_unreadable_subscriptions_send_nothing_and_are_logged(subscriptions: FakeSubscriptions,
                                                              capsys: pytest.CaptureFixture[str]) -> None:
    log = Logged(capsys)
    subscriptions.down = True
    sender = FakeSender()
    pushed(sender, queued())
    assert sender.sends == [] and len(log.events("push.subscriptions_unavailable")) == 1


def test_drain_takes_only_push_threads_each_poll(outbox: FakeOutbox, subscriptions: FakeSubscriptions) -> None:
    subscribed(subscriptions, ALANA, 1)
    subscribed(subscriptions, SAM, 2)
    outbox.waiting = [waiting(thread(ALANA), "one", id_=1, medium="text"), waiting("device:3", "aloud", id_=2),
                      waiting("discord:9", "posted", id_=3, medium="text"), waiting(thread(SAM), "two", id_=4,
                                                                                    medium="text")]
    sender = FakeSender()
    polls = Polls(stop_at=3)

    async def scenario() -> None:
        await drained(drain(sender, CONFIG, 0.25, polls))

    run(scenario())
    assert [(b.endpoint, n.body) for b, n in sender.sends] == [(browser(1).endpoint, "one"), (browser(2).endpoint, "two")]
    assert set(outbox.prefixes) == {"push:"} and polls.waits == [0.25] * 3
    assert [w.thread for w in outbox.waiting] == ["device:3", "discord:9"]
