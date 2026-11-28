"""Two reads the house glance shows a person (`ashley.api.house_attention`), each unknown rather than fine when it cannot be
made: how many printers report a fault, and whether the house does not answer.

Logs `house.attention_unread` with the household and the part that could not be read."""

import logging

from .. import logs, services
from ..home_assistant.homes import Homes, HomesUnavailable
from ..home_assistant.house import HouseUnavailable
from ..printing.model import NotConnected, PrintingFailed, PrintingUnavailable
from ..printing.printing import Printing

log = logging.getLogger("ashley.tools")
PRINTERS_READ = 50


async def printer_faults(household_id: int) -> int | None:
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


async def house_unreadable(household_id: int) -> bool | None:
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
