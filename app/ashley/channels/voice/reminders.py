"""Fired reminders routed to a room, said by the satellites singleton (`later.drain`), which alone holds the
satellites' connections: her stored answer (spoken, since her turn ran on the satellite's thread, `reminder_turn`) with
the household's pronunciation words, played by `saying.said` as a queued reply is. A satellite not connected now is a
try that did not reach them (`how` `not_connected`); after its tries the reminder goes to the phone
(`ashley.channels.wake.device_delivery`)."""

from ... import services
from ...conversations.model import Turn
from ...senses.wakes import Delivery
from ..lexicons import Lexicons
from ..wake import device_delivery
from .run import Pipeline
from .saying import said
from .session import Links

REACHED = frozenset({"room_speaker", "announced"})


async def deliver(links: Links, pipeline: Pipeline) -> int:
    """Try each fired reminder whose next try is in its room; how many were tried."""

    async def spoken(delivery: Delivery, answer: Turn) -> tuple[bool, str]:
        link = None if delivery.device_id is None else links.get(delivery.device_id)
        body = (await services.get(Lexicons).of(delivery.household_id)).respell(answer.text)
        how, _ = await said(body, 0, link, pipeline)
        return how in REACHED, how

    return await device_delivery.deliver("room", spoken)
