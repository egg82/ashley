"""The household's printers as a signed-in person's cards read them (`GET /api/house/printers`), from the read the house
glance makes (`channels.kiosk.glance_reads.printers_now`)."""

from ..channels.kiosk.glance_reads import printers_now
from .house_models import HousePrinter, HousePrinters


async def printers(household_id: int) -> HousePrinters:
    found = await printers_now(household_id)
    if found is None:
        return HousePrinters(printers=None)
    return HousePrinters(printers=[HousePrinter(
        printer_id=p.id, name=p.name, printer_model=p.model, online=p.online, state=p.state, print_name=p.job, percent=p.percent,
        minutes_left=p.minutes_left, layer=p.layer, layers=p.layers, problems=[f.text or f.code for f in p.faults])
        for p in found])
