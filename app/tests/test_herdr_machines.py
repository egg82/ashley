"""A person with several herdr bridges, one per machine, each named by its connection label: the default machine is the
first made, a label that is not the person's own is refused, her tools list every machine's sessions and take the
machine for what acts on one, a watch finds its session on whichever machine has it and never reads a machine that did
not answer as the session ended, focus is the latest typing on any machine, and a session piece names its machine."""

import asyncio
import json
from collections.abc import Generator
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest
from ashley import services
from ashley.api import claude_screen
from ashley.api.claude_screen import SessionScreen
from ashley.api.person import person_signed_in
from ashley.connections.connections import Connections
from ashley.connections.kinds import ConnectionKinds
from ashley.connections.model import Connection, Opened
from ashley.herdr import machines
from ashley.herdr.bridge import Bridge, NullBridge
from ashley.herdr.machines import MachineRefused
from ashley.herdr.model import Access, BridgeFailed, Screen, Session, SessionList, Status
from ashley.inference.model import ToolCall
from ashley.main import create_app
from ashley.senses.focus import FocusUnavailable
from ashley.senses.herdr_focus import HerdrFocus
from ashley.settings import Settings
from ashley.signin.model import SignedIn
from ashley.tools import claude_code_config
from ashley.tools.claude_code import ClaudeCodeTools
from ashley.watches.claude_session import ClaudeSession
from ashley.watches.model import ReadFailed
from ashley.wiring import CONNECTION_KINDS
from ashley.workshop import session_piece
from fastapi.testclient import TestClient
from money_support import EPOCH, HeldConnections
from respond_support import ALANA as PERSON
from watch_job_support import watch

HOME, ME, OTHER_PERSON = PERSON.household_id, PERSON.id, 99
ID = "0a1b2c3d-0000-4000-8000-00000000abcd"
ELSEWHERE = "0a1b2c3d-0000-4000-8000-00000000ffff"
CONFIG = claude_code_config.load()


def origin(name: str) -> str:
    return f"https://{name}.test:7843"


def address(name: str) -> str:
    return f"{origin(name)}#sha256={'0' * 64}"


@dataclass
class Host:
    """What one machine's bridge answers, found by its origin."""

    sessions: tuple[Session, ...] = ()
    typed: str | None = None
    down: bool = False


@dataclass
class Bridges(NullBridge):
    hosts: dict[str, Host] = field(default_factory=dict[str, Host])
    reads: list[str] = field(default_factory=list[str])

    async def sessions(self, access: Access) -> SessionList:
        host = self.hosts[access.origin]
        if host.down:
            raise BridgeFailed("herdr_unavailable")
        return SessionList(host.sessions, host.typed, ("/work",))

    async def read(self, access: Access, session_id: str, lines: int) -> Screen:
        self.reads.append(access.origin)
        return Screen(f"screen of {access.origin}", False, 1)


def sess(session_id: str = ID, label: str = "fix", status: Status = "idle") -> Session:
    return Session(session_id, label, "/work/p", status, 3, None)


@pytest.fixture
def held() -> Generator[HeldConnections]:
    made = HeldConnections()
    services.register(Connections, made)
    services.register(ConnectionKinds, ConnectionKinds(CONNECTION_KINDS))
    yield made
    for service in (Connections, Bridge, ConnectionKinds):
        services.unregister(service)


def add(held: HeldConnections, number: int, label: str, person: int = ME) -> None:
    connection = Connection(number, HOME, "herdr", address(label or "unnamed"), person, EPOCH, EPOCH, person, label)
    held.held[(HOME, f"herdr:{person}:{label}")] = Opened(connection, "tok")


@pytest.fixture
def two(held: HeldConnections) -> Bridges:
    """The person's `laptop` made second and `vm` first, and another person's `desk`; each bridge lists its own session."""
    add(held, 2, "laptop")
    add(held, 1, "vm")
    add(held, 3, "desk", OTHER_PERSON)
    bridges = Bridges({origin("vm"): Host((sess(ID, "on-vm"),), "2026-11-13T10:00:00+00:00"),
                       origin("laptop"): Host((sess(ELSEWHERE, "on-laptop"),), "2026-11-13T11:00:00+00:00"),
                       origin("desk"): Host((sess("0a1b2c3d-0000-4000-8000-000000000001", "theirs"),))})
    services.register(Bridge, bridges)
    return bridges


def say(name: str, args: dict[str, object]) -> tuple[bool, str]:
    got = asyncio.run(ClaudeCodeTools(HOME, ME, CONFIG, 10000).call(ToolCall("c", name, args)))
    return got.is_error, got.content


def test_the_first_made_is_the_default_and_a_label_not_the_persons_own_is_refused(two: Bridges) -> None:
    held = asyncio.run(machines.held(HOME, ME))
    assert [m.label for m in held] == ["vm", "laptop"]
    chosen = machines.choose(held, None)
    assert chosen is not None and chosen.label == "vm"
    chosen = machines.choose(held, "laptop")
    assert chosen is not None and chosen.label == "laptop"
    with pytest.raises(MachineRefused) as e:
        machines.choose(held, "desk")
    assert e.value.reason == "unknown_machine"
    with pytest.raises(MachineRefused) as e:
        machines.choose(held, None, must_name=True)
    assert e.value.reason == "machine_needed"
    assert machines.choose((), None) is None


def test_sessions_of_every_machine_are_listed_by_machine_and_one_that_is_down_is_shown(two: Bridges) -> None:
    failed, text = say("claude_sessions", {})
    body = json.loads(text)
    assert not failed
    assert {(r["machine"], r["label"]) for r in body["sessions"]} == {("vm", "on-vm"), ("laptop", "on-laptop")}
    assert [m["machine"] for m in body["machines"]] == ["vm", "laptop"]
    two.hosts[origin("laptop")].down = True
    body = json.loads(say("claude_sessions", {})[1])
    assert [r["machine"] for r in body["sessions"]] == ["vm"]
    assert [(m["machine"], m["reachable"]) for m in body["machines"]] == [("vm", True), ("laptop", False)]


def test_a_named_machine_lists_only_its_own_and_acts_there(two: Bridges) -> None:
    body = json.loads(say("claude_sessions", {"machine": "laptop"})[1])
    assert [r["label"] for r in body["sessions"]] == ["on-laptop"] and body["roots"] == ["/work"]
    failed, text = say("claude_read", {"session": ELSEWHERE, "machine": "laptop"})
    assert not failed and two.reads == [origin("laptop")] and "laptop" in text


def test_a_call_that_acts_must_name_the_machine_when_there_are_several_and_the_name_must_be_the_persons(two: Bridges) -> None:
    failed, text = say("claude_read", {"session": ID})
    assert failed and text.startswith("machine_needed:")
    failed, text = say("claude_read", {"session": ID, "machine": "desk"})
    assert failed and text.startswith("unknown_machine:")
    assert two.reads == []


def test_with_one_machine_none_is_named(held: HeldConnections) -> None:
    add(held, 1, "vm")
    services.register(Bridge, Bridges({origin("vm"): Host((sess(),))}))
    failed, text = say("claude_read", {"session": ID})
    assert not failed and "vm" in text


def test_a_watch_finds_its_session_on_any_machine_and_a_machine_that_is_down_is_not_the_session_ending(two: Bridges) -> None:
    def read(target: str) -> object:
        return asyncio.run(ClaudeSession().read([watch(1, target=target, person=ME, household=HOME)]))[1]

    assert read(ELSEWHERE) == {ELSEWHERE: {"status": "idle", "seq": 3}}
    assert read("0a1b2c3d-0000-4000-8000-0000000000aa") == {}
    two.hosts[origin("laptop")].down = True
    assert read(ELSEWHERE) == ReadFailed("unreachable")
    assert read(ID) == {ID: {"status": "idle", "seq": 3}}


def test_focus_is_the_latest_typing_on_any_machine_and_a_machine_that_is_off_is_skipped(two: Bridges) -> None:
    assert asyncio.run(HerdrFocus().typed_at(HOME, ME)) == datetime(2026, 11, 13, 11, tzinfo=UTC)
    two.hosts[origin("laptop")].down = True
    assert asyncio.run(HerdrFocus().typed_at(HOME, ME)) == datetime(2026, 11, 13, 10, tzinfo=UTC)
    two.hosts[origin("vm")].down = True
    with pytest.raises(FocusUnavailable):
        asyncio.run(HerdrFocus().typed_at(HOME, ME))


def test_a_session_piece_names_its_machine_or_none() -> None:
    plain = json.dumps({"source": "herdr", "session": ID})
    named = json.dumps({"source": "herdr", "session": ID, "machine": "laptop"})
    assert session_piece.reference_of(plain) == session_piece.SessionRef("herdr", ID, None)
    assert session_piece.reference_of(named) == session_piece.SessionRef("herdr", ID, "laptop")
    for bad in ({"machine": ""}, {"machine": 7}, {"machine": "x" * 41}, {"machine": None}, {"machine": "a", "extra": 1}):
        assert session_piece.reference_of(json.dumps({"source": "herdr", "session": ID, **bad})) is None, bad


def test_the_screen_route_reads_the_machine_the_piece_names(held: HeldConnections, two: Bridges) -> None:
    app = create_app(Settings(database_url="", build_version="test", public_url="https://ashley.test"))
    services.register(Connections, held)   # create_app wires its own
    services.register(Bridge, two)
    services.register(ConnectionKinds, ConnectionKinds(CONNECTION_KINDS))
    app.dependency_overrides[person_signed_in] = lambda: SignedIn(1, PERSON)
    c = TestClient(app, base_url="https://ashley.test")

    def screen(**params: str) -> SessionScreen:
        got = c.get(f"/api/claude/sessions/{ELSEWHERE}/screen", params=params)
        assert got.status_code == 200, got.text
        return SessionScreen.model_validate(got.json())

    assert screen(machine="laptop").state == "live" and screen(machine="laptop").text == f"screen of {origin('laptop')}"
    assert screen().state == "gone"   # the default machine, the vm, does not list it
    assert screen(machine="desk").state == "unknown_machine"
    assert claude_screen.CONFIG.screen_lines > 0
