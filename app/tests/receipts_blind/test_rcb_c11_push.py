"""Contract 11 as the orchestrator override states it: a reply is one notification, her words only, with the Agree action
on it when a proposal is held, never a second one; a receipt-only reply (voice) is one notification of the headlines with
Agree when held."""

import pytest
from ashley.channels.model import Outbound
from ashley.channels.outbox import Later
from ashley.channels.push import config as push_config
from ashley.channels.push.later import push, thread
from ashley.channels.push.subscriptions import Subscription
from ashley.conversations.model import Receipt, Receipts
from contract.conversations_support import run
from push_support import FakeSender, FakeSubscriptions, browser, subscriptions as subscriptions

CONFIG = push_config.load()
DONE = Receipts((Receipt("RB-did-lamp", "house_do (action: light.turn_on)", "RB-because"),), (), None)
HELD = Receipts((Receipt("RB-did-lamp", None, None),), (Receipt("RB-held-mail", 'mail_label (folder: "archive")', None),), 41)
HER_WORDS = "Okay, I did one thing and one waits."


def queued(receipts: Receipts | None, body: str = HER_WORDS) -> Later:
    return Later(1, 1, thread(1), Outbound(5, "text", body, receipts=receipts), 100)


def sent(subs: FakeSubscriptions, later: Later) -> FakeSender:
    subs.rows.append(Subscription(1, 1, 1, browser(1)))
    sender = FakeSender()
    run(push(sender, CONFIG, later))
    return sender


@pytest.mark.parametrize("receipts", [None, DONE, HELD])
def test_c11_a_reply_is_one_notification_of_her_words_only(subscriptions: FakeSubscriptions, receipts: Receipts | None) -> None:
    sender = sent(subscriptions, queued(receipts))
    ((_, note),) = sender.sends
    assert note.body == HER_WORDS
    for r in (() if receipts is None else (*receipts.done, *receipts.held)):
        assert not [s for s in (r.headline, r.detail, r.why) if s and s in note.body]


def test_c11_agree_is_on_her_notification_when_a_proposal_is_held_and_not_otherwise(subscriptions: FakeSubscriptions) -> None:
    ((_, held),) = sent(subscriptions, queued(HELD)).sends
    assert held.agree == 41
    subscriptions.rows.clear()
    ((_, done),) = sent(subscriptions, queued(DONE)).sends
    assert done.agree is None


def test_c11_a_long_reply_is_cut_as_ever_and_keeps_its_agree_action(subscriptions: FakeSubscriptions) -> None:
    long_words = "word " * (CONFIG.body_chars)
    ((_, note),) = sent(subscriptions, queued(HELD, long_words)).sends
    assert len(note.body) <= CONFIG.body_chars and note.agree == 41


def test_c11_a_receipt_only_reply_is_one_notification_of_the_headlines_with_agree_when_held(
        subscriptions: FakeSubscriptions) -> None:
    ((_, note),) = sent(subscriptions, queued(HELD, "")).sends
    assert "RB-did-lamp" in note.body and "RB-held-mail" in note.body and note.agree == 41
    assert note.title == CONFIG.held_title


def test_c11_a_receipt_only_reply_of_a_done_change_has_the_done_title_and_no_agree(subscriptions: FakeSubscriptions) -> None:
    ((_, note),) = sent(subscriptions, queued(DONE, "")).sends
    assert "RB-did-lamp" in note.body and note.agree is None and note.title == CONFIG.done_title
