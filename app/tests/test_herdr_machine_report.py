"""A machine as she picks it: `claude_machines` gives each machine's name, the description its person wrote, and the
report its bridge reads live, a machine whose report cannot be read is listed without one and says why, a field the
bridge could not read stays null, and the tool's result counts as words from outside because a USB name is a device's."""

import asyncio
import json
from collections.abc import Generator
from dataclasses import dataclass, field, replace
from typing import Any

import pytest
from ashley import services
from ashley.connections.connections import Connections
from ashley.connections.kinds import ConnectionKinds
from ashley.connections.model import Connection, Opened
from ashley.herdr.bridge import Bridge, NullBridge
from ashley.herdr.model import Access, BridgeFailed, Gpu, MachineReport, Session, SessionList, UsbDevice
from ashley.herdr.wire import machine as parse_machine
from ashley.inference.model import ToolCall
from ashley.tools import claude_code_config
from ashley.tools.claude_code import ClaudeCodeTools
from ashley.wiring import CONNECTION_KINDS
from money_support import EPOCH, HeldConnections

HOME, ME = 1, 7
CONFIG = claude_code_config.load()
BENCH = "The personal workstation, in the office near the workbench"


def report(**changes: object) -> MachineReport:
    base = MachineReport("ws", "Test Linux", "6.1", "Test CPU", 16, 32000, 21000, (Gpu("Test GPU", 24576),), False,
                         ("pio", "python3"), (UsbDevice("1a86:7523", "USB Serial"),))
    return replace(base, **changes)


@dataclass
class Bridges(NullBridge):
    reports: dict[str, MachineReport | str] = field(default_factory=dict[str, MachineReport | str])

    async def machine(self, access: Access) -> MachineReport:
        got = self.reports[access.origin]
        if isinstance(got, str):
            raise BridgeFailed("not_found" if got == "old" else "herdr_unavailable")
        return got

    async def sessions(self, access: Access) -> SessionList:
        return SessionList((Session("0a1b2c3d-0000-4000-8000-00000000abcd", "x", "/w", "idle", 1, None),), None, ("/w",))


def add(held: HeldConnections, number: int, label: str, description: str) -> None:
    connection = Connection(number, HOME, "herdr", f"https://{label}.test:7843#sha256={'0' * 64}", ME, EPOCH, EPOCH, ME,
                            label, description=description)
    held.held[(HOME, f"herdr:{ME}:{label}")] = Opened(connection, "tok")


@pytest.fixture
def machines() -> Generator[Bridges]:
    held = HeldConnections()
    add(held, 1, "workstation", BENCH)
    add(held, 2, "vm", "")
    add(held, 3, "laptop", "The travel laptop")
    bridges = Bridges({"https://workstation.test:7843": report(), "https://vm.test:7843": "old",
                       "https://laptop.test:7843": "down"})
    services.register(Connections, held)
    services.register(ConnectionKinds, ConnectionKinds(CONNECTION_KINDS))
    services.register(Bridge, bridges)
    yield bridges
    for service in (Connections, Bridge, ConnectionKinds):
        services.unregister(service)


def say(name: str, args: dict[str, object]) -> tuple[bool, Any]:
    got = asyncio.run(ClaudeCodeTools(HOME, ME, CONFIG, 10000).call(ToolCall("c", name, args)))
    return got.is_error, json.loads(got.content) if not got.is_error else {"error": got.content}


def test_each_machine_is_given_with_its_description_and_report(machines: Bridges) -> None:
    failed, body = say("claude_machines", {})
    assert not failed
    rows = {r["machine"]: r for r in body["machines"]}
    assert list(rows) == ["workstation", "vm", "laptop"]
    ws = rows["workstation"]
    assert ws["description"] == BENCH
    assert ws["report"]["gpus"] == [{"model": "Test GPU", "memory_mb": 24576}]
    assert ws["report"]["tools"] == ["pio", "python3"] and ws["report"]["memory_mb"] == {"total": 32000, "available": 21000}
    assert ws["report"]["usb"] == [{"id": "1a86:7523", "product": "USB Serial"}]


def test_a_machine_that_cannot_report_is_listed_without_one_and_says_why(machines: Bridges) -> None:
    rows = {r["machine"]: r for r in say("claude_machines", {})[1]["machines"]}
    assert rows["vm"]["report"] is None and "too old" in rows["vm"]["report_unavailable"]
    assert rows["laptop"]["report"] is None and rows["laptop"]["report_unavailable"] == "it did not answer"
    assert rows["laptop"]["description"] == "The travel laptop"


def test_a_named_machine_is_the_only_one_read_and_a_stranger_is_refused(machines: Bridges) -> None:
    body = say("claude_machines", {"machine": "workstation"})[1]
    assert [r["machine"] for r in body["machines"]] == ["workstation"]
    failed, text = say("claude_machines", {"machine": "desk"})
    assert failed and str(text["error"]).startswith("unknown_machine:")


def test_a_field_the_bridge_could_not_read_stays_null_not_zero(machines: Bridges) -> None:
    machines.reports["https://workstation.test:7843"] = report(gpus=None, usb=None, busy=None, memory_total_mb=None)
    got = say("claude_machines", {"machine": "workstation"})[1]["machines"][0]["report"]
    assert got["gpus"] is None and got["usb"] is None and got["session_busy"] is None
    assert got["memory_mb"]["total"] is None


def test_the_sessions_list_names_each_machine_with_its_description(machines: Bridges) -> None:
    shown = say("claude_sessions", {})[1]["machines"]
    assert {m["machine"]: m["description"] for m in shown} == {"workstation": BENCH, "vm": "", "laptop": "The travel laptop"}


def test_the_tool_is_outside_words_and_the_session_list_is_not(machines: Bridges) -> None:
    specs = {s.name: s for s in asyncio.run(ClaudeCodeTools(HOME, ME, CONFIG, 10000).catalogue()).specs}
    assert specs["claude_machines"].outside and not specs["claude_sessions"].outside


def test_the_bridges_body_is_read_with_nulls_kept() -> None:
    raw = json.dumps({"hostname": "ws", "cpu": {"model": "C", "cores": 4}, "memory": {"total_mb": 8},
                      "gpus": [], "busy": None, "tools": ["pio"], "usb": [{"id": "1a86:7523"}], "future": 1}).encode()
    got = parse_machine(raw)
    assert (got.cpu_cores, got.memory_total_mb, got.memory_available_mb, got.os) == (4, 8, None, None)
    assert got.gpus == () and got.busy is None and got.usb == (UsbDevice("1a86:7523", None),)
    assert parse_machine(b'{"hostname": "ws", "gpus": null, "usb": null}').gpus is None
    with pytest.raises(BridgeFailed):
        parse_machine(b'{"tools": "pio"}')
