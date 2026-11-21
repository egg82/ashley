"""`printing_queue` end to end through `PrintQueueTools` and the Bambuddy adapter, against a fake Bambuddy built from its
OpenAPI document: it is offered as a change (tier `asks`), only to a household with a printing manager; an item is
always sent staged (`manual_start`) with the AMS slots she suggests as Bambuddy's global tray ids and the plate she names;
what Bambuddy turns away comes back as a typed outcome (`not_found`, `rejected`), a key that may not queue as `refused`;
what the person agrees to is written by code from the manager as it stands and holds no file name."""

import asyncio
import json
from collections.abc import Coroutine, Iterator
from typing import Any

import httpx2
import pytest
from ashley import services
from ashley.bambuddy import queueing, wire
from ashley.bambuddy.client import Bambuddy, BambuddyFailed, HttpBambuddy
from ashley.bambuddy.printing import BambuddyPrinting
from ashley.connections.connections import Connections
from ashley.inference.model import ToolCall, ToolResult
from ashley.printing.model import Placement
from ashley.printing.printing import Printing
from ashley.tools import printing_config
from ashley.tools.printing_queue import PrintQueueTools
from ashley.tools.printing_queue_specs import QUEUE
from ashley.tools.tools import ToolsUnavailable, Unshown
from bambuddy_support import BASE, KEY, FakeBambuddy, held, status
from mail_bridge_support import logged

HOME = 10
CONFIG = printing_config.load()
ASK: dict[str, object] = {"file_id": "2", "printer_id": "1"}
PHONE_STAND = "Phone stand"


@pytest.fixture
def fake() -> Iterator[FakeBambuddy]:
    found = FakeBambuddy()
    services.register(Connections, held(HOME))
    services.register(Bambuddy, found.client())
    services.register(Printing, BambuddyPrinting())
    yield found


def tools(household: int = HOME) -> PrintQueueTools:
    return PrintQueueTools(household, CONFIG)


def queue(**arguments: object) -> ToolResult:
    return asyncio.run(tools().call(ToolCall("c1", QUEUE, arguments)))


def body(result: ToolResult) -> dict[str, Any]:
    assert not result.is_error, result.content
    loose: dict[str, Any] = json.loads(result.content)
    return loose


def shown(**arguments: object) -> str | None:
    return asyncio.run(tools().shown(ToolCall("c1", QUEUE, arguments)))


def test_the_queue_is_a_change_offered_only_where_there_is_a_manager(fake: FakeBambuddy) -> None:
    (spec,) = asyncio.run(tools().catalogue()).specs
    assert (spec.name, spec.reads, spec.outside, spec.tier) == (QUEUE, False, False, "asks")
    assert asyncio.run(tools(HOME + 1).catalogue()).specs == ()
    assert asyncio.run(tools(HOME + 1).call(ToolCall("c", QUEUE, ASK))).content.startswith("not_connected")


def test_an_item_goes_in_staged_with_nothing_else_unless_she_names_it(fake: FakeBambuddy) -> None:
    got = body(queue(**ASK))
    assert got == {"outcome": "queued", "item_id": "101", "position": 1, "staged": True}
    assert fake.queued == [{"printer_id": 1, "library_file_id": 2, "manual_start": True}]


def test_her_slots_and_plate_become_the_global_tray_ids_and_the_plate(fake: FakeBambuddy) -> None:
    assert body(queue(**ASK, plate=2, slots=[{"need": 2, "unit": 1, "slot": 4}]))["outcome"] == "queued"
    both = body(queue(**ASK, slots=[{"need": 1, "unit": 1, "slot": 1}, {"need": 2, "unit": 1, "slot": 2}]))
    assert both["outcome"] == "queued"
    assert fake.queued[0] == {"printer_id": 1, "library_file_id": 2, "manual_start": True, "plate_id": 2,
                              "ams_mapping": [-1, 3]}
    assert fake.queued[1]["ams_mapping"] == [0, 1] and fake.queued[1]["manual_start"] is True


def test_an_ams_ht_unit_is_addressed_by_its_own_id() -> None:
    ams = status()["ams"]
    assert isinstance(ams, list)
    two = wire.Status.model_validate({**status(), "ams": [*ams, {"id": 128, "humidity": 2, "tray": [{"id": 0}]}]})
    assert queueing.mapping_of(two, (Placement(1, 2, 1), Placement(3, 1, 4))) == [128, -1, 3]
    assert queueing.mapping_of(two, (Placement(1, 3, 1),)) is None and queueing.mapping_of(two, (Placement(1, 2, 2),)) is None


def test_a_file_or_printer_that_is_not_there_is_not_found(fake: FakeBambuddy) -> None:
    assert body(queue(file_id="99", printer_id="1")) == {"outcome": "not_found"}
    assert body(queue(file_id="2", printer_id="7")) == {"outcome": "not_found"}
    assert body(queue(file_id="2", printer_id="7", slots=[{"need": 1, "unit": 1, "slot": 1}])) == {"outcome": "not_found"}
    assert fake.queued == []


def test_what_bambuddy_would_not_queue_is_rejected(fake: FakeBambuddy) -> None:
    fake.unsliced.add(2)
    assert body(queue(**ASK)) == {"outcome": "rejected"}
    fake.unsliced.clear()
    assert body(queue(**ASK, slots=[{"need": 1, "unit": 1, "slot": 9}])) == {"outcome": "rejected"}
    assert fake.queued == [] and ("/api/v1/queue/", {}, "the-households-print-key") not in fake.seen[-1:]


@pytest.mark.parametrize(("failure", "outcome"), [("forbidden", "refused"), ("key", "refused"), ("down", "unreachable"),
                                                   ("html", "not_bambuddy")])
def test_a_manager_that_fails_is_an_error_result_that_names_why(fake: FakeBambuddy, failure: str, outcome: str) -> None:
    if failure == "forbidden":
        fake.forbidden.add("/api/v1/queue/")
    elif failure == "key":
        fake.key = "another"
    elif failure == "down":
        fake.answers["/api/v1/queue/"] = None
        fake.status = 503
    else:
        fake.raw = b"<html>"
    got = queue(**ASK)
    assert got.is_error and got.content.startswith(outcome) and fake.queued == []


def test_a_key_that_may_not_queue_is_told_so_and_a_link_that_cannot_be_read_is_unavailable(fake: FakeBambuddy) -> None:
    fake.forbidden.add("/api/v1/queue/")
    assert "may not queue prints" in queue(**ASK).content
    down = held(HOME)
    down.down = True
    services.register(Connections, down)
    assert queue(**ASK).content.startswith("unavailable")
    with pytest.raises(ToolsUnavailable):
        asyncio.run(tools().catalogue())


@pytest.mark.parametrize("arguments", [
    {"printer_id": "1"}, {"file_id": "2"}, {"file_id": "x", "printer_id": "1"}, {"file_id": "2", "printer_id": 1},
    {**ASK, "plate": 0}, {**ASK, "plate": "1"}, {**ASK, "plate": True}, {**ASK, "slots": "1"}, {**ASK, "slots": [1]},
    {**ASK, "slots": [{"need": 1, "unit": 1}]}, {**ASK, "slots": [{"need": 0, "unit": 1, "slot": 1}]},
    {**ASK, "slots": [{"need": 1, "unit": 1, "slot": 1}, {"need": 1, "unit": 1, "slot": 2}]},
    {**ASK, "slots": [{"need": n + 1, "unit": 1, "slot": 1} for n in range(CONFIG.placements_max + 1)]},
])
def test_wrong_arguments_ask_bambuddy_nothing(fake: FakeBambuddy, arguments: dict[str, object]) -> None:
    got = queue(**arguments)
    assert got.is_error and got.content.startswith("bad_arguments") and fake.seen == []
    with pytest.raises(Unshown):
        shown(**arguments)


def test_what_the_person_agrees_to_is_written_from_the_manager_and_holds_no_file_name(fake: FakeBambuddy) -> None:
    assert shown(**ASK) == ("Queue library file 2 (3mf, 1 h 0 min, 12.5 g) on Shed X1C. It waits, staged, until someone "
                            "starts it in Bambuddy")
    line = shown(**ASK, plate=2, slots=[{"need": 1, "unit": 1, "slot": 1}, {"need": 2, "unit": 1, "slot": 4}])
    assert line == ("Queue library file 2 (3mf, 1 h 0 min, 12.5 g) on Shed X1C, plate 2; filament 1 from AMS 1 slot 1 "
                    "(PLA); filament 2 from AMS 1 slot 4 (PLA), not the type the file is sliced for. It waits, staged, "
                    "until someone starts it in Bambuddy")
    assert PHONE_STAND not in str(line) and fake.queued == []


@pytest.mark.parametrize(("arguments", "told"), [
    ({"file_id": "99", "printer_id": "1"}, "printing_files lists"),
    ({"file_id": "2", "printer_id": "7"}, "printing_printers lists"),
    ({**ASK, "slots": [{"need": 1, "unit": 1, "slot": 9}]}, "printing_ams and printing_needs"),
    ({**ASK, "slots": [{"need": 5, "unit": 1, "slot": 1}]}, "printing_ams and printing_needs"),
])
def test_a_print_that_cannot_be_shown_says_why(fake: FakeBambuddy, arguments: dict[str, object], told: str) -> None:
    with pytest.raises(Unshown, match=told):
        shown(**arguments)


def test_a_manager_that_cannot_be_read_shows_nothing(fake: FakeBambuddy) -> None:
    fake.status = 503
    with pytest.raises(Unshown, match="could not be read"):
        shown(**ASK)


def test_the_log_carries_the_path_and_no_name_or_key(fake: FakeBambuddy, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("INFO")
    queue(**ASK)
    lines = logged(caplog)
    assert [f["path"] for m, f in lines if m == "bambuddy.post"] == ["/api/v1/queue/"]
    assert "the-households-print-key" not in str(lines) and PHONE_STAND not in str(lines)


@pytest.mark.parametrize(("status", "write", "read"), [(422, "rejected", "unreachable"), (415, "rejected", "unreachable"),
                                                      (404, "not_found", "not_found"), (500, "unreachable", "unreachable"),
                                                      (403, "refused", "refused")])
def test_only_a_write_is_ever_rejected(status: int, write: str, read: str) -> None:
    client = HttpBambuddy(httpx2.AsyncClient(transport=httpx2.MockTransport(lambda r: httpx2.Response(status, json={}))), 5, 5)

    def reason(call: Coroutine[Any, Any, object]) -> str:
        with pytest.raises(BambuddyFailed) as failed:
            asyncio.run(call)
        return failed.value.reason

    assert reason(client.get(BASE, KEY, "/api/v1/printers/", {})) == read
    assert reason(client.post(BASE, KEY, "/api/v1/queue/", {})) == write
    assert reason(client.upload(BASE, KEY, "/api/v1/library/files", "a.stl", b"x")) == write
