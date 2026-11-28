"""What of the house needs a person (`HouseAttention`), each part read on its own so one that cannot be read shows as unknown
and never as nothing wrong. Logs `house.attention_unread` with the household and the part that could not be read."""

import logging

from .. import logs, services
from ..errands.bench_jobs import JobsUnavailable
from ..errands.errands import ErrandsUnavailable
from ..home_assistant.homes import Homes, HomesUnavailable
from ..home_assistant.house import HouseUnavailable
from ..people.people import PeopleUnavailable
from ..printing.model import NotConnected, PrintingFailed, PrintingUnavailable
from ..printing.printing import Printing
from ..senses.wakes import WakesUnavailable
from ..workshop.model import Owner
from ..workshop.workshop import WorkshopUnavailable
from .house_models import HouseAttention
from .work_items import open_work

log = logging.getLogger("ashley.api")
PRINTERS_READ = 50


async def attention(owner: Owner) -> HouseAttention:
    return HouseAttention(waiting_on_you=await _waiting(owner), printer_faults=await _faults(owner.household_id),
                          house_unreadable=await _unreadable(owner.household_id))


async def _waiting(owner: Owner) -> int | None:
    try:
        return sum(1 for i in await open_work(owner) if i.state == "waiting_on_you")
    except (ErrandsUnavailable, WakesUnavailable, JobsUnavailable, WorkshopUnavailable, PeopleUnavailable):
        logs.info(log, "house.attention_unread", household=owner.household_id, part="work")
        return None


async def _faults(household_id: int) -> int | None:
    """How many printers report a fault; None with no printing manager, when it cannot be read, or when it holds more
    printers than were read."""
    try:
        page = await services.get(Printing).printers(household_id, PRINTERS_READ)
    except NotConnected:
        return None
    except (PrintingFailed, PrintingUnavailable):
        logs.info(log, "house.attention_unread", household=household_id, part="printers")
        return None
    return sum(1 for p in page.rows if p.faults) if page.total <= len(page.rows) else None


async def _unreadable(household_id: int) -> bool | None:
    """Whether the house did not answer; None when the household has no house."""
    try:
        home = await services.get(Homes).of(household_id)
        if home is None:
            return None
        await home.house.states()
    except (HomesUnavailable, HouseUnavailable):
        logs.info(log, "house.attention_unread", household=household_id, part="house")
        return True
    return False
