"""Contract 8: `Catalogue.now` is placed in the moment layer only, never in `stable`; a Composite joins it like
instructions, in source order."""

import asyncio
from dataclasses import replace
from datetime import datetime
from typing import get_args
from zoneinfo import ZoneInfo

from ashley.conversations.model import Kind
from ashley.inference.model import ToolCall, ToolResult, ToolSpec
from ashley.people.model import Household, Person
from ashley.persona.persona import Context, system
from ashley.tools.composite import CompositeTools
from ashley.tools.tools import Catalogue, Tools

ALANA = Person(1, 1, "Alana")
HOME = Household(1, "home", "America/Denver", "A profile line.", (ALANA,))
NOW = datetime(2026, 10, 25, 19, 34, tzinfo=ZoneInfo("America/Denver"))
CONTEXT = Context(NOW, HOME, ALANA, frozenset({1}), "kitchen", "Tool guidance.", True)
MARK = "BENCH-STATE-MARK-71"
AWAY = "While you were away the lamp was switched on."
SPEC = ToolSpec("t", "t", {"type": "object"})


class Source(Tools):
    def __init__(self, name: str, now: str | None) -> None:
        self._spec, self._now = ToolSpec(name, name, {"type": "object"}), now

    async def catalogue(self) -> Catalogue:
        return Catalogue((self._spec,), f"how to use {self._spec.name}", now=self._now)

    async def call(self, call: ToolCall) -> ToolResult:
        return ToolResult(call.id, "ok")


def test_c8_a_catalogue_has_no_now_unless_its_source_gives_one() -> None:
    assert Catalogue((SPEC,), None).now is None
    assert Catalogue((SPEC,), None, now="x").now == "x"


def test_c8_the_state_is_in_the_moment_layer_for_every_kind() -> None:
    for kind in get_args(Kind):
        prompt = system(kind, replace(CONTEXT, tools_now=MARK))["default"]
        assert MARK in prompt.moment and MARK not in prompt.stable


def test_c8_the_stable_layer_is_the_same_with_and_without_it_so_the_cached_prefix_is_untouched() -> None:
    for kind in get_args(Kind):
        with_it = system(kind, replace(CONTEXT, tools_now=MARK))["default"]
        without = system(kind, CONTEXT)["default"]
        assert with_it.stable == without.stable


def test_c8_without_it_the_moment_is_what_it_was() -> None:
    assert MARK not in system("chat", CONTEXT)["default"].moment
    assert system("chat", replace(CONTEXT, tools_now=None)) == system("chat", CONTEXT)


def test_c8_it_follows_the_asks_done_while_she_was_away() -> None:
    moment = system("chat", replace(CONTEXT, tools_now=MARK, while_away=(AWAY,)))["default"].moment
    assert moment.index(AWAY) < moment.index(MARK)


def test_c8_a_composite_joins_each_sources_now_in_source_order() -> None:
    both = CompositeTools({"first": Source("a", "FIRST-STATE"), "second": Source("b", "SECOND-STATE")})
    got = asyncio.run(both.catalogue()).now
    assert got is not None and got.index("FIRST-STATE") < got.index("SECOND-STATE")
    flipped = CompositeTools({"second": Source("b", "SECOND-STATE"), "first": Source("a", "FIRST-STATE")})
    again = asyncio.run(flipped.catalogue()).now
    assert again is not None and again.index("SECOND-STATE") < again.index("FIRST-STATE")


def test_c8_a_source_with_no_now_adds_nothing_and_none_at_all_is_none() -> None:
    mixed = asyncio.run(CompositeTools({"a": Source("a", None), "b": Source("b", "ONLY-STATE")}).catalogue()).now
    assert mixed is not None and "ONLY-STATE" in mixed and "None" not in mixed
    assert asyncio.run(CompositeTools({"a": Source("a", None), "b": Source("b", None)}).catalogue()).now is None
