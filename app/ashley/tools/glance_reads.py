"""Reads of the house a person's screens show (`ashley.api.house_attention`, `ashley.api.house_printers`), each unknown
rather than fine when it cannot be made: how many printers report a fault, the printers themselves, and whether the house
does not answer.

Logs `house.attention_unread` with the household and the part that could not be read, and `house.printers_unread` with
the household when the printers could not be read for their card."""

import logging

from .. import logs, services
from ..home_assistant.homes import Homes, HomesUnavailable
from ..home_assistant.house import HouseUnavailable
from ..printing.model import NotConnected, Printer, PrintingFailed, PrintingUnavailable
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


async def printers_now(household_id: int) -> tuple[Printer, ...] | None:
    """The household's printers as they are now, empty with no printing manager; None when they cannot be read, or when
    it holds more than were read, so a printer left out is never taken for one that is not there."""
    try:
        page = await services.get(Printing).printers(household_id, PRINTERS_READ)
    except NotConnected:
        return ()
    except (PrintingFailed, PrintingUnavailable):
        logs.info(log, "house.printers_unread", household=household_id)
        return None
    return page.rows if page.total <= len(page.rows) else None


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
