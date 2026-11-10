"""Each household's everyday tools (`tools.everyday`): a household with a Home Assistant gets the tools built over its
own house, built once per Home and again once its Home is replaced; one without gets the locator's `Tools`; a
household's house unreadable is ToolsUnavailable from the catalogue and an error result from a call. `HouseholdTools`
resolves its household once and answers as those tools do."""

import asyncio
from collections.abc import Generator

import pytest
from ashley import services
from ashley.home_assistant.client import HomeAssistant
from ashley.home_assistant.homes import Home, Homes
from ashley.inference.model import ToolCall, ToolResult, ToolSpec
from ashley.tools.everyday import Everyday, HomesEveryday, HouseholdTools
from ashley.tools.tools import Catalogue, Tools, ToolsUnavailable
from homes_support import ByHousehold


class Named(Tools):
    def __init__(self, name: str) -> None:
        self.name = name
        self.calls: list[str] = []

    async def catalogue(self) -> Catalogue:
        return Catalogue((ToolSpec(self.name, self.name, {"type": "object"}),), None)

    async def call(self, call: ToolCall) -> ToolResult:
        self.calls.append(call.name)
        return ToolResult(call.id, self.name)


@pytest.fixture
def house() -> Generator[ByHousehold]:
    made = ByHousehold()
    services.register(Homes, made)
    services.register(Tools, Named("look_up"))
    yield made
    for interface in (Homes, Tools, Everyday):
        services.unregister(interface)


def built() -> tuple[HomesEveryday, list[HomeAssistant]]:
    over: list[HomeAssistant] = []

    def build(home: Home) -> Tools:
        over.append(home.home_assistant)
        return Named(f"house{len(over)}")

    return HomesEveryday(build), over


def names(tools: Tools) -> list[str]:
    return [s.name for s in asyncio.run(tools.catalogue()).specs]


def test_a_household_with_a_house_gets_tools_over_its_own_built_once(house: ByHousehold) -> None:
    everyday, over = built()
    one = house.give(1, "http://one.test")
    two = house.give(2, "http://two.test")

    async def scenario() -> None:
        first = await everyday.of(1)
        assert await everyday.of(1) is first
        assert await everyday.of(2) is not first

    asyncio.run(scenario())
    assert over == [one.home_assistant, two.home_assistant]


def test_a_replaced_home_gets_its_tools_built_again(house: ByHousehold) -> None:
    everyday, over = built()
    house.give(1, "http://one.test")
    first = asyncio.run(everyday.of(1))
    replaced = house.give(1, "http://one.test")
    assert asyncio.run(everyday.of(1)) is not first and over[-1] is replaced.home_assistant


def test_a_household_without_a_house_gets_the_locators_tools(house: ByHousehold) -> None:
    everyday, over = built()
    assert asyncio.run(everyday.of(3)) is services.get(Tools) and over == []


def test_a_house_unreadable_is_unavailable(house: ByHousehold) -> None:
    everyday, _ = built()
    house.down = True
    with pytest.raises(ToolsUnavailable):
        asyncio.run(everyday.of(1))


def test_the_null_everyday_answers_the_locators_tools(house: ByHousehold) -> None:
    assert asyncio.run(Everyday.null().of(1)) is services.get(Tools)


def test_household_tools_answer_as_their_households_tools_resolving_once(house: ByHousehold) -> None:
    everyday, _ = built()
    services.register(Everyday, everyday)
    house.give(1, "http://one.test")
    tools = HouseholdTools(1)
    assert names(tools) == ["house1"] and names(HouseholdTools(3)) == ["look_up"]
    result = asyncio.run(tools.call(ToolCall("c1", "house1", {})))
    assert result == ToolResult("c1", "house1") and house.asked == [1, 3]


def test_household_tools_whose_house_is_unreadable_raise_from_the_catalogue_and_answer_calls_with_an_error(
        house: ByHousehold) -> None:
    everyday, _ = built()
    services.register(Everyday, everyday)
    house.down = True
    tools = HouseholdTools(1)
    with pytest.raises(ToolsUnavailable):
        asyncio.run(tools.catalogue())
    result = asyncio.run(tools.call(ToolCall("c1", "HassTurnOn", {})))
    assert result.is_error and result.call_id == "c1"
