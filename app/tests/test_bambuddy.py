"""Bambuddy as a connection kind and as the adapter of the Printing and Stock services: what is asked and with what, each
failure's typed reason, Bambuddy's bodies turned into neutral records, and a household with no connection not connected."""

import asyncio
import traceback
from collections.abc import Coroutine, Iterator
from typing import Any

import httpx2
import pytest
from ashley import services
from ashley.bambuddy.check import printers_seen
from ashley.bambuddy.client import Bambuddy, BambuddyFailed, HttpBambuddy, base_url
from ashley.bambuddy.kind import BAMBUDDY
from ashley.bambuddy.printing import BambuddyPrinting
from ashley.bambuddy.stock import BambuddyStock
from ashley.connections.connections import Connections
from ashley.connections.kinds import ConnectionKinds
from ashley.printing.model import NotConnected as PrintingNotConnected, PrintingFailed, PrintingUnavailable
from ashley.printing.printing import NullPrinting, Printing
from ashley.stock.model import NotConnected as StockNotConnected, StockFailed
from ashley.stock.stock import NullStock, Stock
from bambuddy_support import BASE, KEY, FakeBambuddy, held, library_file, printer, spool, status

HOME = 10


@pytest.fixture
def fake() -> Iterator[FakeBambuddy]:
    found = FakeBambuddy()
    services.register(Connections, held(HOME))
    services.register(Bambuddy, found.client())
    services.register(Printing, BambuddyPrinting())
    services.register(Stock, BambuddyStock())
    yield found


def run[T](coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coro)


def test_the_kind_serves_both_ports_and_is_http_or_https() -> None:
    kinds = services.get(ConnectionKinds)
    assert [k.name for k in kinds.of_port("printing")] == ["bambuddy"]
    assert [k.name for k in kinds.of_port("stock")] == ["bambuddy"]
    assert BAMBUDDY.secret_field == "api_key" and BAMBUDDY.schemes == {"http", "https"}
    assert base_url("http://192.0.2.5:8080/") == "http://192.0.2.5:8080" and base_url("ftp://x.test") is None


def test_the_key_goes_in_the_api_key_header_and_only_reads_are_made(fake: FakeBambuddy) -> None:
    methods: list[str] = []

    def handle(request: httpx2.Request) -> httpx2.Response:
        methods.append(request.method)
        return fake.handle(request)

    client = HttpBambuddy(httpx2.AsyncClient(transport=httpx2.MockTransport(handle)), 5)
    assert run(client.get(BASE, KEY, "/api/v1/printers/", {})) == fake.answers["/api/v1/printers/"]
    assert methods == ["GET"] and fake.seen == [("/api/v1/printers/", {}, KEY)]


@pytest.mark.parametrize(("status", "reason"), [(401, "refused"), (403, "refused"), (404, "not_found"),
                                                (500, "unreachable"), (302, "unreachable")])
def test_each_status_is_a_typed_reason(status: int, reason: str) -> None:
    with pytest.raises(BambuddyFailed) as got:
        run(FakeBambuddy(status=status).client().get(BASE, KEY, "/api/v1/printers/", {}))
    assert got.value.reason == reason


def test_a_page_that_is_not_json_is_not_bambuddy_and_the_key_is_in_no_traceback() -> None:
    with pytest.raises(BambuddyFailed) as got:
        run(FakeBambuddy(raw=b"<html>").client().get(BASE, KEY, "/api/v1/printers/", {}))
    assert got.value.reason == "not_bambuddy" and KEY not in "".join(traceback.format_exception(got.value))


def test_the_check_counts_printers_and_refuses_what_is_not_bambuddy(fake: FakeBambuddy) -> None:
    assert run(printers_seen(BASE, KEY)) == 1
    fake.answers["/api/v1/printers/"] = {"printers": []}
    with pytest.raises(BambuddyFailed) as got:
        run(printers_seen(BASE, KEY))
    assert got.value.reason == "not_bambuddy"


def test_an_unwired_household_is_not_connected_to_either_service() -> None:
    assert isinstance(services.get(Printing), NullPrinting) and isinstance(services.get(Stock), NullStock)
    with pytest.raises(PrintingNotConnected):
        run(services.get(Printing).printers(HOME, 5))
    with pytest.raises(StockNotConnected):
        run(services.get(Stock).spools(HOME, 5))


def test_a_household_with_no_connection_is_not_connected(fake: FakeBambuddy) -> None:
    assert run(services.get(Printing).connected(HOME)) is True and run(services.get(Stock).connected(HOME)) is True
    assert run(services.get(Printing).connected(HOME + 1)) is False
    with pytest.raises(PrintingNotConnected):
        run(services.get(Printing).printers(HOME + 1, 5))


def test_printers_become_records_with_their_ams_and_the_spool_recorded_in_a_slot(fake: FakeBambuddy) -> None:
    got = run(services.get(Printing).printers(HOME, 5))
    [printer] = got.rows
    assert got.total == 1
    assert (printer.id, printer.name, printer.model, printer.online, printer.state) == ("1", "Shed X1C", "X1C", True,
                                                                                         "RUNNING")
    assert (printer.job, printer.percent, printer.minutes_left, printer.layer, printer.layers) == ("Benchy", 42.0, 95,
                                                                                                     80, 190)
    assert [(f.code, f.text) for f in printer.faults] == [("0300_0100_0002_0001", "Heatbed temperature abnormal")]
    [unit] = printer.ams
    assert (unit.unit, unit.humidity) == (1, 3)
    assert [(s.slot, s.material, s.colour, s.remaining_percent, s.spool_id, s.empty) for s in unit.slots] == [
        (1, "PLA", "#FF0000", 80, "7", False), (2, "PETG", "#00FF00", None, None, False),
        (3, None, None, None, None, True), (4, "PLA", "#FFFFFF", 55, None, False)]


def test_an_idle_printer_has_no_print_fields(fake: FakeBambuddy) -> None:
    fake.answers["/api/v1/printers/1/status"] = status(state="IDLE", name_of_print=None)
    [printer] = run(services.get(Printing).printers(HOME, 5)).rows
    assert (printer.state, printer.job, printer.percent, printer.minutes_left, printer.layer) == ("IDLE", None, None,
                                                                                                  None, None)


def test_printers_over_the_limit_are_cut_and_only_the_shown_are_asked(fake: FakeBambuddy) -> None:
    fake.answers["/api/v1/printers/"] = [printer(i, f"Shed {i}") for i in (1, 2, 3)]
    got = run(services.get(Printing).printers(HOME, 1))
    assert (len(got.rows), got.total) == (1, 3)
    assert [p for p, _, _ in fake.seen if p.endswith("/status")] == ["/api/v1/printers/1/status"]


@pytest.mark.parametrize("how", ["missing", "refused"])
def test_a_household_without_recorded_spools_still_reads_its_printers(fake: FakeBambuddy, how: str) -> None:
    path = "/api/v1/spoolman/inventory/slot-assignments/all"
    (fake.missing if how == "missing" else fake.forbidden).add(path)
    [printer] = run(services.get(Printing).printers(HOME, 5)).rows
    assert [s.spool_id for s in printer.ams[0].slots] == [None] * 4


def test_the_files_are_searched_newest_first_in_any_case_and_cut(fake: FakeBambuddy) -> None:
    got = run(services.get(Printing).files(HOME, "BENCHY", 1))
    assert [f.name for f in got.rows] == ["Benchy Boat Mk2"] and got.total == 2
    assert fake.seen[-1][:2] == ("/api/v1/library/files", {"include_root": "false"})
    every = run(services.get(Printing).files(HOME, None, 10))
    assert [f.id for f in every.rows] == ["3", "2", "1"]
    f = every.rows[1]
    assert (f.kind, f.print_seconds, f.grams, f.printer_model, f.prints) == ("3mf", 3600, 12.5, "X1C", 2)
    assert library_file(9, "x")["print_name"] == "x"


def test_a_files_needs_are_read_and_an_unknown_file_is_none(fake: FakeBambuddy) -> None:
    got = run(services.get(Printing).needs(HOME, "2"))
    assert got is not None
    assert [(n.slot, n.material, n.colour, n.grams) for n in got] == [(1, "PLA", "#FF0000", 10.5),
                                                                       (2, "PETG", "#00FF00", 2.0)]
    assert run(services.get(Printing).needs(HOME, "99")) is None
    run(services.get(Printing).needs(HOME, "../../x"))
    assert fake.seen[-1][0] == "/api/v1/library/files/..%2F..%2Fx/filament-requirements"


@pytest.mark.parametrize(("status", "reason"), [(401, "refused"), (500, "unreachable")])
def test_a_failing_bambuddy_is_the_ports_reason(status: int, reason: str, fake: FakeBambuddy) -> None:
    services.register(Bambuddy, FakeBambuddy(status=status).client())
    with pytest.raises(PrintingFailed) as printing:
        run(services.get(Printing).printers(HOME, 5))
    with pytest.raises(StockFailed) as stock:
        run(services.get(Stock).spools(HOME, 5))
    assert printing.value.reason == reason and stock.value.reason == reason


def test_a_body_that_is_not_bambuddys_is_unrecognised(fake: FakeBambuddy) -> None:
    fake.answers["/api/v1/printers/"] = {"printers": []}
    with pytest.raises(PrintingFailed) as got:
        run(services.get(Printing).printers(HOME, 5))
    assert got.value.reason == "unrecognised"
    fake.missing.add("/api/v1/printers/")
    with pytest.raises(PrintingFailed) as gone:
        run(services.get(Printing).printers(HOME, 5))
    assert gone.value.reason == "unrecognised"


def test_the_connections_link_being_down_is_unavailable(fake: FakeBambuddy) -> None:
    down = held(HOME)
    down.down = True
    services.register(Connections, down)
    with pytest.raises(PrintingUnavailable):
        run(services.get(Printing).connected(HOME))


def test_the_stock_is_the_unarchived_spools_most_left_first(fake: FakeBambuddy) -> None:
    got = run(services.get(Stock).spools(HOME, 10))
    assert got.total == 3 and [s.id for s in got.rows] == ["10", "7", "8"]
    first, second, third = got.rows
    assert (first.remaining_grams, first.full_grams, first.colour, first.location) == (1000, 1000, None, None)
    assert (second.material, second.brand, second.colour_name, second.colour, second.remaining_grams,
            second.location) == ("PLA", "Acme", "Red", "#FF0000", 750, "Shelf 2")
    assert third.remaining_grams == 100
    assert fake.seen[-1][0] == "/api/v1/spoolman/inventory/spools"
    cut = run(services.get(Stock).spools(HOME, 1))
    assert (len(cut.rows), cut.total) == (1, 3)


def test_a_spool_used_past_its_label_has_nothing_left_not_less(fake: FakeBambuddy) -> None:
    fake.answers["/api/v1/spoolman/inventory/spools"] = [spool(1, used=1200.0)]
    [got] = run(services.get(Stock).spools(HOME, 5)).rows
    assert got.remaining_grams == 0


def test_a_request_without_the_api_key_header_is_turned_away(fake: FakeBambuddy) -> None:
    http = httpx2.Client(transport=httpx2.MockTransport(fake.handle))
    assert http.get(BASE + "/api/v1/printers/", headers={"Authorization": f"Bearer {KEY}"}).status_code == 401
    assert http.get(BASE + "/api/v1/printers/", headers={"X-API-Key": KEY}).status_code == 200
