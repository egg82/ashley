"""A reply that shows a held proposal reaches the person's browsers with its id, so the notification offers Agree: the
`Outbound.agree` a reply was queued with survives the outbox, rides to every browser in the payload, and a reply that
shows no proposal carries none."""

import json

import pytest
from ashley.channels.model import Outbound
from ashley.channels.outbox import Later, Outbox
from ashley.channels.postgres_outbox import PostgresOutbox
from ashley.channels.push import config as push_config
from ashley.channels.push import sender as sender_module
from ashley.channels.push.later import push, thread
from ashley.channels.push.sender import Notification, Sent, WebPushSender
from ashley.channels.push.subscriptions import Subscription
from ashley.conversations.postgres import PostgresConversations
from ashley.db.pool import PoolDatabase
from contract.conversations_support import POLICY, db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import household, person, run
from push_support import FakeSender, FakeSubscriptions, browser, subscriptions as subscriptions
from test_push_config import key_pair, settings

CONFIG = push_config.load()


def queued(agree: int | None) -> Later:
    return Later(1, 1, thread(1), Outbound(5, "text", "Waiting for your OK, not done yet:\n- switch", agree=agree), 100)


@pytest.mark.parametrize("agree", [41, None])
def test_the_notification_carries_the_proposal_its_reply_shows(subscriptions: FakeSubscriptions, agree: int | None) -> None:
    subscriptions.rows.append(Subscription(1, 1, 1, browser(1)))
    sender = FakeSender()
    run(push(sender, CONFIG, queued(agree)))
    ((_, sent),) = sender.sends
    assert sent.agree == agree and isinstance(sent, Notification)


def test_the_payload_a_browser_receives_names_the_proposal(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    def fake_webpush(info: dict[str, object], **kwargs: object) -> None:
        calls.append(kwargs)

    monkeypatch.setattr(sender_module, "webpush", fake_webpush)
    public, private = key_pair()
    identity = push_config.vapid(settings(public, private))
    assert identity is not None
    got: list[Sent] = []

    async def scenario() -> None:
        got.append(await WebPushSender(identity, 600, 2).send(browser(1), Notification("Ashley", "hi", "/", 41)))

    run(scenario())
    assert got == [Sent("ok", 201)]
    assert json.loads(str(calls[0]["data"])) == {"title": "Ashley", "body": "hi", "url": "/", "agree": 41}


def test_the_outbox_keeps_the_proposal_with_the_reply(db_url: str) -> None:
    async def go() -> None:
        db = PoolDatabase(db_url, connect_timeout_s=5.0)
        await db.open()
        try:
            home = household(db_url)
            who = person(db_url, home)
            conversation = await PostgresConversations(db, POLICY).for_thread(
                home, f"person:{who}:web", "chat", [who], remembered=True, channel="web", place=None)
            box: Outbox = PostgresOutbox(db, 600.0, POLICY)
            await box.add(home, thread(who), Outbound(conversation.id, "text", "a", agree=41))
            await box.add(home, thread(who), Outbound(conversation.id, "text", "b"))
            got = await box.take("push:")
            assert [(later.outbound.body, later.outbound.agree) for later in got] == [("a", 41), ("b", None)]
        finally:
            await db.close()
    run(go())
