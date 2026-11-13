"""Whether a reply may go to the speaker's phone (`decisions.md`, "Web push"): to a known speaker with at least one
subscribed browser, on a spoken channel or on a turn she was woken for (`Inbound.unprompted`) that is not already on
their phone thread, and only when the model sets `Reply.to_phone`. Then `text` is queued for `push:<speaker id>` and
`spoken` plays as usual. Otherwise the field is ignored. On a woken turn she is also told whether the person has a
page open on either site (`looking`), so she routes by what she knows; code never pushes for her.

Logs `push.to_phone` (conversation, person, outcome: `queued`, `not_offered`) for each reply that
sets the field. Never text. Subscriptions that cannot be read are not logged here: with push off that is every spoken
turn, and a database that is down shows in the turn's other systems."""

import logging

from .. import logs, services
from ..conversations.model import Receipts
from ..inference.reply import Reply
from ..live.live import load as live_config
from ..live.screens import Screens, ScreensUnavailable
from ..people.model import Person
from .model import Inbound, Outbound
from .outbox import Pushed
from .push.later import PREFIX as PUSH_PREFIX, thread
from .push.subscriptions import Subscriptions, SubscriptionsUnavailable

log = logging.getLogger("ashley.channels")
PRESENT_S = live_config().present_s


async def reachable(inbound: Inbound, speaker: Person | None) -> int | None:
    """The speaker's id when this reply may offer their phone; None when the channel is not spoken, the speaker is
    unknown, or they have no browser subscribed (or it could not be read)."""
    if speaker is None or not (inbound.medium == "spoken" or _woken(inbound)):
        return None
    try:
        browsers, _ = await services.get(Subscriptions).count(speaker.id)
    except SubscriptionsUnavailable:
        return None
    return speaker.id if browsers else None


def _woken(inbound: Inbound) -> bool:
    """A turn she was woken for, on a thread other than their phone's, which a push would only repeat; never a remark."""
    return inbound.unprompted and inbound.remark is None and not inbound.thread.startswith(PUSH_PREFIX)


async def looking(inbound: Inbound, speaker: Person | None) -> bool | None:
    """On a woken turn, whether a screen of the speaker's is open on any pod of either site (`Screens`); None when
    that is not a fact this turn is given: another kind of turn, an unknown speaker, or a record that cannot be read."""
    if speaker is None or not _woken(inbound):
        return None
    try:
        return await services.get(Screens).looking(speaker.id, PRESENT_S)
    except ScreensUnavailable:
        return None


def copy(reply: Reply, phone: int | None, household_id: int, conversation_id: int,
         receipts: Receipts | None = None) -> Pushed | None:
    """`reply.text` to queue for the phone of `phone`, the speaker `reachable` offered (None: not offered); None when
    the reply does not go there. The caller queues it in the transaction that stores her turn (`Outbox.answer`), so a
    turn resumed after a kill queues it once. It carries `receipts`, which the notification reaches by a tap through
    to the page, and the Agree action for the proposal they hold."""
    if not reply.to_phone:
        return None
    if phone is None:
        logs.info(log, "push.to_phone", conversation=conversation_id, outcome="not_offered")
        return None
    logs.info(log, "push.to_phone", conversation=conversation_id, person=phone, outcome="queued")
    return Pushed(household_id, thread(phone), Outbound(
        conversation_id, "text", reply.text, receipts=receipts))
