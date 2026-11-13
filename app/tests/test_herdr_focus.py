"""Focus from a person's herdr bridge (`ashley.senses.herdr_focus.HerdrFocus`): the list's latest typing time, None
when they have no bridge or it records none, and FocusUnavailable when the connections or the bridge cannot be read,
so a remark waiting on focus never takes "could not read" for "not typing"."""

import asyncio
from collections.abc import Generator
from datetime import UTC, datetime

import pytest
from ashley import services
from ashley.connections.connections import Connections
from ashley.herdr.bridge import Bridge, NullBridge
from ashley.herdr.model import Access, BridgeFailed, SessionList
from ashley.senses.focus import FocusUnavailable
from ashley.senses.herdr_focus import HerdrFocus
from money_support import HeldConnections

HOME, ALANA = 1, 5
PIN = "0" * 64


class Listing(NullBridge):
    def __init__(self, typed: str | None = None, failed: BridgeFailed | None = None) -> None:
        self.typed, self.failed, self.asked = typed, failed, list[Access]()

    async def sessions(self, access: Access) -> SessionList:
        self.asked.append(access)
        if self.failed is not None:
            raise self.failed
        return SessionList((), self.typed)


@pytest.fixture
def held() -> Generator[HeldConnections]:
    made = HeldConnections()
    services.register(Connections, made)
    try:
        yield made
    finally:
        services.unregister(Connections)
        services.unregister(Bridge)


def _typed(bridge: Bridge) -> datetime | None:
    services.register(Bridge, bridge)
    return asyncio.run(HerdrFocus().typed_at(HOME, ALANA))


def test_the_bridges_latest_typing_is_when_they_typed(held: HeldConnections) -> None:
    held.connect(HOME, f"https://127.0.0.1:7843#sha256={PIN}", "token", "herdr", ALANA)
    bridge = Listing("2026-11-13T11:58:00+00:00")
    assert _typed(bridge) == datetime(2026, 11, 13, 11, 58, tzinfo=UTC)
    assert [a.person for a in bridge.asked] == [ALANA]
    assert _typed(Listing("2026-11-13T11:58:00")) == datetime(2026, 11, 13, 11, 58, tzinfo=UTC)


def test_no_bridge_or_no_typing_recorded_is_no_typing(held: HeldConnections) -> None:
    assert _typed(Listing("2026-11-13T11:58:00+00:00")) is None
    held.connect(HOME, f"https://127.0.0.1:7843#sha256={PIN}", "token", "herdr", ALANA)
    assert _typed(Listing(None)) is None


def test_a_bridge_or_connections_that_cannot_be_read_is_unavailable(held: HeldConnections) -> None:
    held.connect(HOME, f"https://127.0.0.1:7843#sha256={PIN}", "token", "herdr", ALANA)
    for bridge in (Listing(failed=BridgeFailed("herdr_unavailable")), Listing("not a time")):
        with pytest.raises(FocusUnavailable):
            _typed(bridge)
    held.down = True
    with pytest.raises(FocusUnavailable):
        _typed(Listing("2026-11-13T11:58:00+00:00"))
