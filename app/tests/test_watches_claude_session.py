"""The claude_session kind reads one Bridge.sessions call per person and keeps each watch's target."""

import asyncio
from collections.abc import Mapping

import pytest
from ashley import services
from ashley.connections.connections import Connections
from ashley.herdr.bridge import Bridge
from ashley.herdr.model import Access, BridgeFailed, Reason, OutFile, Screen, Session, SessionList, Whoami
from ashley.watches.claude_session import ClaudeSession
from ashley.watches.model import FailReason, Read, ReadFailed
from money_support import HeldConnections
from watch_job_support import session, watch

PIN = "0" * 64
BASE = f"https://bridge.test:7843#sha256={PIN}"


class FakeBridge(Bridge):
    def __init__(self, sessions: tuple[Session, ...] = (), fail: Reason | None = None) -> None:
        self.found = sessions
        self.fail: Reason | None = fail
        self.asked = 0

    async def sessions(self, access: Access) -> SessionList:
        self.asked += 1
        if self.fail is not None:
            raise BridgeFailed(self.fail)
        return SessionList(self.found, None)

    async def whoami(self, access: Access) -> Whoami:
        raise AssertionError("not used")

    async def read(self, access: Access, session_id: str, lines: int) -> Screen:
        raise AssertionError("not used")

    async def prompt(self, access: Access, session_id: str, text: str) -> None:
        raise AssertionError("not used")

    async def start(self, access: Access, directory: str, label: str, model: str | None) -> Session:
        raise AssertionError("not used")

    async def close(self, access: Access, session_id: str) -> None:
        raise AssertionError("not used")

    async def upload(self, access: Access, session_id: str, name: str, data: bytes) -> None:
        raise AssertionError("not used")

    async def outputs(self, access: Access, session_id: str) -> tuple[OutFile, ...]:
        raise AssertionError("not used")

    async def download(self, access: Access, session_id: str, name: str, max_bytes: int) -> bytes:
        raise AssertionError("not used")


def world(bridge: FakeBridge, connected: bool = True) -> None:
    held = HeldConnections()
    if connected:
        held.connect(1, BASE, "tok", "herdr", 7)
    services.register(Connections, held)
    services.register(Bridge, bridge)


def read(*ids: int, targets: tuple[str, ...] = ("s1",)) -> Mapping[int, Read]:
    group = [watch(i, target=t) for i, t in zip(ids, targets)]
    return asyncio.run(ClaudeSession().read(group))


def test_one_call_serves_every_watch_of_the_person_and_each_keeps_its_target() -> None:
    bridge = FakeBridge((Session("s1", "a", "/d", "working", 4, None), Session("s2", "b", "/d", "done", 9, None)))
    world(bridge)
    got = read(1, 2, targets=("s1", "s2"))
    assert bridge.asked == 1
    assert got == {1: session("working", 4), 2: session("done", 9, "s2")}


def test_a_target_the_bridge_does_not_list_is_gone() -> None:
    world(FakeBridge((Session("s2", "b", "/d", "done", 9, None),)))
    assert read(1) == {1: {}}


def test_no_connection_is_not_connected_for_every_watch() -> None:
    bridge = FakeBridge()
    world(bridge, connected=False)
    assert read(1, 2, targets=("s1", "s2")) == {1: ReadFailed("not_connected"), 2: ReadFailed("not_connected")}
    assert bridge.asked == 0


@pytest.mark.parametrize(("reason", "slug"), [
    ("herdr_unavailable", "unreachable"), ("unconfirmed", "unreachable"), ("bad_token", "refused"),
    ("wrong_person", "refused"), ("pin_mismatch", "refused"), ("unexpected", "bad_result"),
    ("bad_request", "bad_result")])
def test_a_bridge_failure_maps_to_the_specs_slug(reason: Reason, slug: FailReason) -> None:
    world(FakeBridge(fail=reason))
    assert read(1) == {1: ReadFailed(slug)}


def test_an_address_without_a_pin_is_bad_result() -> None:
    held = HeldConnections()
    held.connect(1, "https://bridge.test:7843", "tok", "herdr", 7)
    services.register(Connections, held)
    services.register(Bridge, FakeBridge())
    assert read(1) == {1: ReadFailed("bad_result")}
