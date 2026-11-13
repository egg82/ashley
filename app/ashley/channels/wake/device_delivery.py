"""Trying fired reminders at the room or screen their route names, for the singleton that can reach it: the satellites
singleton for a `room` (`ashley.channels.voice.reminders`), the push singleton for a `screen` (`screen_delivery`). Each
try reads her stored answer, claims the try (`Wakes.claim`, so a pod taking over mid-tries never tries twice at once)
and records whether it reached them (`Wakes.delivered`); after `device_tries` tries not reached it is the phone's
(`ashley.channels.push.reminders`). The state is all in the reminder's row, so any pod on either site resumes it.

Logs `reminder.at_device` per try: wake, device, route, attempt and outcome (`delivered`, `undelivered`, `kept_quiet`,
`no_answer`, `claimed_elsewhere`) plus the reaching side's own `how`; `reminder.at_device_unavailable` when the
reminders or her answer could not be read. Never text."""

import logging
from collections.abc import Awaitable, Callable

from ... import logs, services
from ...conversations.conversations import Conversations, ConversationsUnavailable
from ...conversations.model import Turn
from ...conversations.quiet import QUIET
from ...senses.wakes import Delivery, Route, Wakes, WakesUnavailable
from .config import CONFIG as WAKES

log = logging.getLogger("ashley.channels.wake")
BATCH = 20

Reach = Callable[[Delivery, Turn], Awaitable[tuple[bool, str]]]
"""Try to reach them with her answer at `Delivery.device_id`: whether it reached them, and how, for the log."""


async def deliver(at: Route, reach: Reach) -> int:
    """Try each fired reminder whose next try is `at`; how many were tried."""
    try:
        due = await services.get(Wakes).undelivered(BATCH, WAKES.retry_s, WAKES.deliver_for_s, at=at,
                                                    device_tries=WAKES.device_tries,
                                                    device_retry_s=WAKES.device_retry_s)
    except WakesUnavailable:
        logs.warning(log, "reminder.at_device_unavailable", route=at, reason="wakes")
        return 0
    tried = 0
    for delivery in due:
        tried += await _tried(at, reach, delivery)
    return tried


async def _tried(at: Route, reach: Reach, delivery: Delivery) -> int:
    fields = {"wake": delivery.id, "device": delivery.device_id, "route": at}
    try:
        answer = await services.get(Conversations).answer_to(delivery.household_id, f"wake:{delivery.id}")
        if answer is None:
            logs.info(log, "reminder.at_device", **fields, outcome="no_answer")
            return 0
        if not await services.get(Wakes).claim(delivery.id, WAKES.retry_s, at=at, device_tries=WAKES.device_tries,
                                               device_retry_s=WAKES.device_retry_s):
            logs.info(log, "reminder.at_device", **fields, outcome="claimed_elsewhere")
            return 0
        if answer.text == QUIET:
            await services.get(Wakes).delivered(delivery.id, True)
            logs.info(log, "reminder.at_device", **fields, outcome="kept_quiet")
            return 1
        reached, how = await reach(delivery, answer)
        await services.get(Wakes).delivered(delivery.id, reached)
    except (WakesUnavailable, ConversationsUnavailable) as e:
        logs.warning(log, "reminder.at_device_unavailable", **fields, reason=type(e).__name__)
        return 0
    logs.info(log, "reminder.at_device", **fields, attempt=delivery.attempts + 1, how=how,
              outcome="delivered" if reached else "undelivered")
    return 1
