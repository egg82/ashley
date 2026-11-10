"""Sending one notification to a person's browsers, for the outbox's replies (`later`) and fired reminders
(`reminders`): a browser whose push service answers 404 or 410 is forgotten; any other failure keeps it. Logs
`push.send_failed` (person, subscription id, status) per failed send and `push.subscriptions_unavailable` when a
browser could not be updated. Never text, endpoints or keys."""

import logging
from collections.abc import Sequence

from ... import logs, services
from .sender import Notification, Sender
from .subscriptions import Subscription, Subscriptions, SubscriptionsUnavailable

log = logging.getLogger("ashley.channels.push")

URL = "/"
"""The path a click on a notification opens."""


async def sent_to(sender: Sender, browsers: Sequence[Subscription], notification: Notification) -> dict[str, int]:
    """`notification` sent to each of `browsers`: how many took it (`ok`), were `gone` (and are forgotten) or
    `failed`."""
    counts = {"ok": 0, "gone": 0, "failed": 0}
    for browser in browsers:
        counts[await _send(sender, browser, notification)] += 1
    return counts


async def _send(sender: Sender, browser: Subscription, notification: Notification) -> str:
    sent = await sender.send(browser.browser, notification)
    if sent.outcome == "failed":
        logs.warning(log, "push.send_failed", person=browser.person_id, subscription=browser.id,
                     status=sent.status or "none")
        return "failed"
    try:
        if sent.outcome == "gone":
            await services.get(Subscriptions).gone(browser.id)
        else:
            await services.get(Subscriptions).delivered(browser.id)
    except SubscriptionsUnavailable:
        logs.warning(log, "push.subscriptions_unavailable", person=browser.person_id, subscription=browser.id)
    return sent.outcome


def cut(text: str, limit: int) -> str:
    """`text` whole when it fits in `limit` characters; otherwise cut at the last space that leaves room for an
    ellipsis, or mid-word when there is none."""
    text = text.strip()
    if len(text) <= limit:
        return text
    head = text[:limit - 1]
    space = head.rfind(" ")
    return (head[:space] if space > 0 else head).rstrip() + "…"
