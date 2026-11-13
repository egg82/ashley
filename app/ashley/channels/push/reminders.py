"""Fired reminders' pushes, sent by the push singleton (`later.drain`) from her stored answer, and recorded on the
reminder (`ashley.senses.wakes.Wakes.delivered`), so a reminder is never lost silently: one that reached no browser
(none subscribed, or every send failed) is listed `undelivered` at once and tried again every `retry_s` for
`deliver_for_s` after it fired (`ashley.channels.wake.config.CONFIG`); one routed to a room or screen comes here once
it was not reached there (`ashley.senses.wakes.Wakes.undelivered`). Not through the outbox, which deletes what it
hands out and drops what waits past `stale_s`.

Logs `push.reminder` per try: wake, person, attempt, `sent`, `gone`, `failed`, and the outcome (`delivered`,
`undelivered`, `kept_quiet` when she judged it not worth sending, `no_answer` when her answer is not stored yet, or `claimed_elsewhere` when another pass took the try); `push.reminders_unavailable` when the reminders,
her answer or the browsers could not be read. Never text, endpoints or keys."""

import logging

from ... import logs, services
from ...conversations.quiet import QUIET
from ...conversations.conversations import Conversations, ConversationsUnavailable
from ...senses.wakes import Delivery, Wakes, WakesUnavailable
from ..wake.config import CONFIG as WAKES
from .config import Config
from .sending import URL, cut, sent_to
from .plain import plain_text
from .sender import Notification, Sender
from .subscriptions import Subscriptions, SubscriptionsUnavailable

log = logging.getLogger("ashley.channels.push")
BATCH = 20


async def deliver(sender: Sender, config: Config) -> int:
    """Try each fired reminder whose push is due a try; how many were tried."""
    try:
        due = await services.get(Wakes).undelivered(BATCH, WAKES.retry_s, WAKES.deliver_for_s,
                                                    device_tries=WAKES.device_tries)
    except WakesUnavailable:
        logs.warning(log, "push.reminders_unavailable", reason="wakes")
        return 0
    tried = 0
    for delivery in due:
        tried += await _tried(sender, config, delivery)
    return tried


async def _kept_quiet(delivery: Delivery) -> int:
    """She judged the reminder not worth sending: record it done with nothing sent, so it is not tried again."""
    try:
        await services.get(Wakes).delivered(delivery.id, True)
    except WakesUnavailable:
        logs.warning(log, "push.reminders_unavailable", wake=delivery.id, reason="wakes")
        return 0
    logs.info(log, "push.reminder", wake=delivery.id, person=delivery.person_id, outcome="kept_quiet")
    return 1


async def _tried(sender: Sender, config: Config, delivery: Delivery) -> int:
    try:
        answer = await services.get(Conversations).answer_to(delivery.household_id, f"wake:{delivery.id}")
        browsers = await services.get(Subscriptions).of(delivery.household_id, delivery.person_id)
    except (ConversationsUnavailable, SubscriptionsUnavailable) as e:
        logs.warning(log, "push.reminders_unavailable", wake=delivery.id, reason=type(e).__name__)
        return 0
    if answer is None:
        logs.info(log, "push.reminder", wake=delivery.id, person=delivery.person_id, outcome="no_answer")
        return 0
    if answer.text == QUIET:
        return await _kept_quiet(delivery)
    try:
        if not await services.get(Wakes).claim(delivery.id, WAKES.retry_s, device_tries=WAKES.device_tries,
                                               device_retry_s=WAKES.device_retry_s):
            logs.info(log, "push.reminder", wake=delivery.id, person=delivery.person_id, outcome="claimed_elsewhere")
            return 0
    except WakesUnavailable:
        logs.warning(log, "push.reminders_unavailable", wake=delivery.id, reason="wakes")
        return 0
    notification = Notification(config.title, cut(plain_text(answer.text), config.body_chars), URL)
    counts = await sent_to(sender, browsers, notification)
    reached = counts["ok"] > 0
    try:
        await services.get(Wakes).delivered(delivery.id, reached)
    except WakesUnavailable:
        logs.warning(log, "push.reminders_unavailable", wake=delivery.id, reason="wakes")
    logs.info(log, "push.reminder", wake=delivery.id, person=delivery.person_id, attempt=delivery.attempts + 1,
              sent=counts["ok"], gone=counts["gone"], failed=counts["failed"],
              outcome="delivered" if reached else "undelivered")
    return 1
