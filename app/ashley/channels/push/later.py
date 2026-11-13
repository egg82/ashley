"""Replies the `Outbox` holds for push threads (`push:<person id>`), sent by the push singleton, under the lease
`push`, to every browser that person subscribed: title `Config.title`, the reply cut to `Config.body_chars`, a click
opening the app at `/`, with an Agree action when the reply carries a held proposal (`Receipts.proposal_id`). Receipts are
not in the body: a tap through to the page shows them; only a reply that is receipts alone (a spoken turn's) says
their headlines. A browser whose
push service answers 404 or 410 is forgotten; any other failure keeps it.

Logs `push.later` per reply taken: person, conversation, how many browsers it was `sent` to, `gone` and `failed`, and
`age_ms`, how long it waited; `push.send_failed` (person, subscription id, status) per failed send;
`push.subscriptions_unavailable` when a person's browsers could not be read or updated; and `push.outbox_unavailable`
once per run of failed takes. Never text, endpoints or keys."""

import logging
from collections.abc import Awaitable, Callable

from ... import logs, services
from ..model import Outbound
from ..outbox import Later, Outbox, OutboxUnavailable
from ..wake import screen_delivery
from . import reminders
from .config import Config
from .sending import URL, cut, sent_to
from .plain import plain_text
from .sender import Notification, Sender
from .subscriptions import Subscriptions, SubscriptionsUnavailable

log = logging.getLogger("ashley.channels.push")

NAME = "push"
PREFIX = "push:"


def thread(person_id: int) -> str:
    """The outbox thread whose replies go to that person's browsers."""
    return f"{PREFIX}{person_id}"


async def drain(sender: Sender, config: Config, poll_s: float, sleep: Callable[[float], Awaitable[None]]) -> None:
    """Every `poll_s` until cancelled, push each reply waiting for a push thread, then each fired reminder whose push
    is due a try (`reminders.deliver`), and try each routed to a screen (`screen_delivery.deliver`)."""
    failing = False
    while True:
        try:
            waiting = await services.get(Outbox).take(PREFIX)
        except OutboxUnavailable:
            if not failing:
                logs.warning(log, "push.outbox_unavailable")
            failing = True
        else:
            failing = False
            for later in waiting:
                await push(sender, config, later)
        await reminders.deliver(sender, config)
        await screen_delivery.deliver()
        await sleep(poll_s)


def notified(config: Config, outbound: Outbound) -> Notification:
    """The notification for `outbound`: her words under the app's title, with the Agree action for a held proposal;
    when it has no words, only receipts, their headlines under the title for what they hold."""
    receipts = outbound.receipts
    agree = None if receipts is None else receipts.proposal_id
    if outbound.body or receipts is None:
        return Notification(config.title, cut(plain_text(outbound.body), config.body_chars), URL, agree)
    title = config.held_title if receipts.held else config.done_title
    headlines = "; ".join(r.headline for r in (*receipts.done, *receipts.held))
    return Notification(title, cut(headlines, config.body_chars), URL, agree)


async def push(sender: Sender, config: Config, later: Later) -> None:
    rest = later.thread.removeprefix(PREFIX)
    if not rest.isdigit():
        return
    person = int(rest)
    try:
        browsers = await services.get(Subscriptions).of(later.household_id, person)
    except SubscriptionsUnavailable:
        logs.warning(log, "push.subscriptions_unavailable", person=person, conversation=later.outbound.conversation_id)
        return
    notification = notified(config, later.outbound)
    counts = await sent_to(sender, browsers, notification)
    logs.info(log, "push.later", person=person, conversation=later.outbound.conversation_id, sent=counts["ok"],
              gone=counts["gone"], failed=counts["failed"], age_ms=later.age_ms)
