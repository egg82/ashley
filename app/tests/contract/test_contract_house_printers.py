"""`GET /api/house/printers`: the household's printers as a signed-in person's printer card reads them. Printers that
cannot be read are null, never an empty list, so a card shows them as unknown rather than as no printer or idle."""

import pytest
from ashley.api.house_models import HousePrinters
from ashley.printing.model import Fault, NotConnected, Printer, PrintingFailed, PrintingUnavailable
from house_routes_support import World, world as world
from kiosk_support import kiosk as kiosk

RUNNING = Printer("01P", "Workshop P1S", "P1S", True, "RUNNING", "benchy.3mf", 42.5, 31, 120, 300,
                  (Fault("0300_4000", "Nozzle clog"), Fault("0500_0001", None)), ())
QUIET = Printer("02X", "Attic X1C", None, False, None, None, None, None, None, None, (), ())


def read(world: World) -> HousePrinters:
    got = world.get("/api/house/printers")
    assert got.status_code == 200
    return HousePrinters.model_validate(got.json())


def test_each_printer_reads_as_its_card_shows_it(world: World) -> None:
    world.printing.error = None
    world.printing.rows = (RUNNING, QUIET)
    got = read(world).printers
    assert got is not None
    assert [p.model_dump() for p in got] == [
        {"printer_id": "01P", "name": "Workshop P1S", "printer_model": "P1S", "online": True, "state": "RUNNING",
         "print_name": "benchy.3mf", "percent": 42.5, "minutes_left": 31, "layer": 120, "layers": 300,
         "problems": ["Nozzle clog", "0500_0001"]},
        {"printer_id": "02X", "name": "Attic X1C", "printer_model": None, "online": False, "state": None, "print_name": None,
         "percent": None, "minutes_left": None, "layer": None, "layers": None, "problems": []}]


def test_a_household_with_no_printing_manager_has_no_printers(world: World) -> None:
    world.printing.error = NotConnected()
    assert read(world).printers == []


@pytest.mark.parametrize("error", [PrintingFailed("unreachable"), PrintingUnavailable("down")])
def test_printers_that_cannot_be_read_are_null_and_never_empty(world: World, error: Exception) -> None:
    world.printing.error = error
    assert read(world).printers is None


def test_more_printers_than_were_read_are_null_so_a_missing_one_is_unknown(world: World) -> None:
    world.printing.error = None
    world.printing.rows = (RUNNING,)
    world.printing.total = 60
    assert read(world).printers is None


def test_no_session_is_unauthorized(world: World) -> None:
    got = world.kiosk.app.get("/api/house/printers")
    assert got.status_code == 401
