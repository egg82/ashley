"""`Only`: a `Tools` offering just the named tools of another, matched as `Excluding` matches (a Home Assistant
`domain__` prefix included); any other call is `unknown_tool` and never reaches the source."""

import asyncio

import pytest
from ashley import logs

from ashley.inference.model import ToolCall, ToolSpec
from ashley.tools.only import Only
from ashley.tools.tools import Catalogue
from contract.conversations_support import events
from wake_support import Switchboard

TURN_ON = ToolSpec("home__HassTurnOn", "turn on", {"type": "object"}, reads=False)


class House(Switchboard):
    async def catalogue(self) -> Catalogue:
        got = await super().catalogue()
        return Catalogue((*got.specs, TURN_ON), "instructions", unreachable=("search",))


def test_only_the_named_tools_are_listed_and_the_rest_of_the_catalogue_is_kept() -> None:
    got = asyncio.run(Only(House(), ("look", "HassTurnOn")).catalogue())
    assert [s.name for s in got.specs] == ["look", "home__HassTurnOn"]
    assert got.instructions == "instructions" and got.unreachable == ("search",)


def test_a_tool_not_named_is_unknown_and_never_reaches_the_source() -> None:
    house = House()
    only = Only(house, ("look",))
    refused = asyncio.run(only.call(ToolCall("c1", "switch", {})))
    allowed = asyncio.run(only.call(ToolCall("c2", "look", {})))
    assert refused.is_error and "switch" in refused.content and not allowed.is_error
    assert [c.id for c in house.ran] == ["c2"]


def test_no_names_offer_nothing() -> None:
    assert asyncio.run(Only(House(), ()).catalogue()).specs == ()


def test_a_named_tool_the_source_does_not_offer_is_logged_as_a_count(capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    asyncio.run(Only(House(), ("look", "HassTurnOm", "lok")).catalogue())
    asyncio.run(Only(House(), ("look",)).catalogue())
    [line] = events(capsys.readouterr().out, "tools.only_unmatched")
    assert line["count"] == "2" and line["unreachable"] == "1"
    assert "HassTurnOm" not in str(line) and "lok" not in str(line)
