"""A household that removes its Home Assistant connection is not reached again with the old token: the next turn's
everyday tools (`tools.everyday.HouseholdTools` over `HomesEveryday` and `ConnectedHomes`) are the locator's, the old
client is closed, and nothing built over it answers a later turn. Also once it connects again, with a new token."""

import asyncio
from collections.abc import Generator

import pytest
from ashley import services
from ashley.home_assistant.connected_homes import ConnectedHomes
from ashley.home_assistant.homes import Home, Homes
from ashley.inference.model import ToolCall, ToolResult, ToolSpec
from ashley.tools.everyday import Everyday, HomesEveryday, HouseholdTools
from ashley.tools.tools import Catalogue, Tools
from homes_support import StandIn
from money_support import HeldConnections
from connection_legacy_support import remove_of

HOUSE = "http://ha.two.test:8123"


class OverHouse(Tools):
    """Every catalogue and call asks the house once, so the stand-in sees which token reached it."""

    def __init__(self, home: Home) -> None:
        self._http = home.home_assistant.http

    async def catalogue(self) -> Catalogue:
        await self._http.get("/api/states")
        return Catalogue((ToolSpec("HassTurnOn", "on", {"type": "object"}),), None)

    async def call(self, call: ToolCall) -> ToolResult:
        await self._http.post("/api/services/light/turn_on")
        return ToolResult(call.id, "done")


class Web(Tools):
    async def catalogue(self) -> Catalogue:
        return Catalogue((ToolSpec("look_up", "look", {"type": "object"}),), None)

    async def call(self, call: ToolCall) -> ToolResult:
        return ToolResult(call.id, "looked")


@pytest.fixture
def wired() -> Generator[tuple[HeldConnections, StandIn]]:
    connections, stand = HeldConnections(), StandIn(token="old-token")
    services.register(Homes, ConnectedHomes(connections, stand.connect))
    services.register(Everyday, HomesEveryday(OverHouse))
    services.register(Tools, Web())
    yield connections, stand
    for interface in (Homes, Everyday, Tools):
        services.unregister(interface)


def turn(household_id: int) -> tuple[list[str], ToolResult]:
    async def one() -> tuple[list[str], ToolResult]:
        tools = HouseholdTools(household_id)
        names = [s.name for s in (await tools.catalogue()).specs]
        return names, await tools.call(ToolCall("c1", names[0], {}))

    return asyncio.run(one())


def test_after_a_removal_her_next_turn_never_reaches_the_house_with_the_old_token(
        wired: tuple[HeldConnections, StandIn]) -> None:
    connections, stand = wired
    connections.connect(2, HOUSE, "old-token", "home_assistant")
    assert turn(2) == (["HassTurnOn"], ToolResult("c1", "done"))
    before = len(stand.seen)
    asyncio.run(remove_of(connections, 2, "home_assistant"))
    assert turn(2) == (["look_up"], ToolResult("c1", "looked"))
    assert turn(2)[0] == ["look_up"]
    assert len(stand.seen) == before and stand.made[0].is_closed


def test_connected_again_with_a_new_token_her_turn_reaches_it_with_the_new_one(
        wired: tuple[HeldConnections, StandIn]) -> None:
    connections, stand = wired
    connections.connect(2, HOUSE, "old-token", "home_assistant")
    turn(2)
    asyncio.run(remove_of(connections, 2, "home_assistant"))
    turn(2)
    stand.token = "new-token"
    connections.connect(2, HOUSE, "new-token", "home_assistant")
    assert turn(2)[0] == ["HassTurnOn"]
    assert {t for _, _, t in stand.seen[-2:]} == {"new-token"}
