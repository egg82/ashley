"""`CompositeTools`: catalogues merged in source order, sources that did not answer named, calls routed to the
source that offered the name."""

import asyncio

import pytest

from ashley import logs
from ashley.inference.model import ToolCall, ToolResult, ToolSpec
from ashley.tools.composite import CompositeTools
from ashley.tools.tools import Catalogue, Tools, ToolsUnavailable
from search_support import call, events

SCHEMA: dict[str, object] = {"type": "object"}


class Source(Tools):
    def __init__(self, names: tuple[str, ...], instructions: str | None = None, down: bool = False) -> None:
        self.names = names
        self.instructions = instructions
        self.down = down
        self.calls: list[str] = []
        self.listed = 0

    async def catalogue(self) -> Catalogue:
        self.listed += 1
        if self.down:
            raise ToolsUnavailable("down")
        return Catalogue(tuple(ToolSpec(n, n, SCHEMA) for n in self.names), self.instructions)

    async def call(self, call: ToolCall) -> ToolResult:
        self.calls.append(call.name)
        return ToolResult(call.id, f"ran {call.name}")


def test_specs_and_instructions_merge_in_source_order() -> None:
    tools = CompositeTools({"house": Source(("light", "lock"), "Rooms."), "web": Source(("search_web",)),
                            "places": Source(("find_places",), "  Near.  ")})
    catalogue = asyncio.run(tools.catalogue())
    assert [s.name for s in catalogue.specs] == ["light", "lock", "search_web", "find_places"]
    assert catalogue.instructions == "Rooms.\n\nNear."
    assert catalogue.unreachable == ()


def test_sources_that_did_not_answer_are_named_in_order() -> None:
    tools = CompositeTools({"house": Source(("light",), "Rooms.", down=True), "web": Source(("search_web",)),
                            "places": Source(("find_places",), down=True)})
    catalogue = asyncio.run(tools.catalogue())
    assert [s.name for s in catalogue.specs] == ["search_web"]
    assert catalogue.unreachable == ("house", "places") and catalogue.instructions is None


def test_every_source_down_is_unavailable() -> None:
    tools = CompositeTools({"house": Source((), down=True), "web": Source((), down=True)})
    with pytest.raises(ToolsUnavailable):
        asyncio.run(tools.catalogue())


def test_a_duplicate_name_keeps_the_first_source(capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    capsys.readouterr()
    house, web = Source(("search_web", "light")), Source(("search_web",))
    tools = CompositeTools({"house": house, "web": web})

    async def scenario() -> Catalogue:
        catalogue = await tools.catalogue()
        await tools.call(call("search_web"))
        return catalogue

    assert [s.name for s in asyncio.run(scenario()).specs] == ["search_web", "light"]
    assert house.calls == ["search_web"] and web.calls == []
    (line,) = events(capsys.readouterr().out, "tools.duplicate")
    assert (line["tool"], line["kept"], line["dropped"]) == ("search_web", "house", "web")


def test_a_call_routes_to_its_source_fetching_the_catalogue_once_first() -> None:
    house, web = Source(("light",)), Source(("search_web",))
    tools = CompositeTools({"house": house, "web": web})

    async def scenario() -> list[ToolResult]:
        return [await tools.call(call("search_web")), await tools.call(call("light"))]

    assert [r.content for r in asyncio.run(scenario())] == ["ran search_web", "ran light"]
    assert (house.calls, web.calls) == (["light"], ["search_web"])
    assert (house.listed, web.listed) == (1, 1)


def test_an_unknown_name_is_an_error_after_one_fetch(capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    capsys.readouterr()
    house = Source(("light",))
    result = asyncio.run(CompositeTools({"house": house}).call(call("nope")))
    assert result.is_error and result.content == "no tool named nope" and result.call_id == "c1"
    assert house.listed == 1
    (line,) = events(capsys.readouterr().out, "tools.call")
    assert (line["tool"], line["outcome"]) == ("nope", "unknown_tool")


def test_a_call_with_every_source_down_is_unknown_not_raised() -> None:
    result = asyncio.run(CompositeTools({"house": Source(("light",), down=True)}).call(call("light")))
    assert result.is_error and result.content == "no tool named light"
