"""What a turn begins with is counted in `respond.offered`: how many tools and which sources they come from, since a
log field cuts a long list of names: the Composite's catalogue names the sources that answered with a tool."""

import asyncio

import pytest
from ashley import logs
from ashley.channels.respond import respond
from ashley.inference.model import ToolCall, ToolResult, ToolSpec
from ashley.tools.composite import CompositeTools
from ashley.tools.tools import Catalogue, Tools
from ashley.inference.reply import Reply
from contract.conversations_support import events
from respond_support import Fakes, inbound, wired as wired

REPLY = Reply(spoken="It is on.", text="It's on.")


class Offers(Tools):
    def __init__(self, *names: str) -> None:
        self._names = names

    async def catalogue(self) -> Catalogue:
        return Catalogue(tuple(ToolSpec(n, "d", {"type": "object"}) for n in self._names), None)

    async def call(self, call: ToolCall) -> ToolResult:
        return ToolResult(call.id, "ok")


def test_a_composite_names_the_sources_that_offered_a_tool_in_order() -> None:
    got = asyncio.run(CompositeTools({"a": Offers("x"), "empty": Offers(), "b": Offers("y", "z")}).catalogue())
    assert got.sources == ("a", "b") and [s.name for s in got.specs] == ["x", "y", "z"]


def test_offered_logs_how_many_tools_and_from_which_sources(wired: Fakes, capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    wired.inference.script = [REPLY]
    asyncio.run(respond(inbound("hi")))
    (offered,) = events(capsys.readouterr().out, "respond.offered")
    assert offered["tool_count"] == "1" and "sources" in offered
