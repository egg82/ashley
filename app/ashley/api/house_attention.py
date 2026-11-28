"""What of the house needs a person (`HouseAttention`), each part read on its own so one that cannot be read shows as unknown
and never as nothing wrong. Logs `house.attention_unread` with the household and the part that could not be read."""

import logging

from .. import logs
from ..channels.kiosk.glance_reads import house_unreadable, printer_faults
from ..errands.bench_jobs import JobsUnavailable
from ..errands.errands import ErrandsUnavailable
from ..people.people import PeopleUnavailable
from ..senses.wakes import WakesUnavailable
from ..workshop.model import Owner
from ..workshop.workshop import WorkshopUnavailable
from .house_models import HouseAttention
from .work_items import open_work

log = logging.getLogger("ashley.api")


async def attention(owner: Owner) -> HouseAttention:
    return HouseAttention(waiting_on_you=await _waiting(owner), printer_faults=await printer_faults(owner.household_id),
                          house_unreadable=await house_unreadable(owner.household_id))


async def _waiting(owner: Owner) -> int | None:
    try:
        return sum(1 for i in await open_work(owner) if i.state == "waiting_on_you")
    except (ErrandsUnavailable, WakesUnavailable, JobsUnavailable, WorkshopUnavailable, PeopleUnavailable):
        logs.info(log, "house.attention_unread", household=owner.household_id, part="work")
        return None
