"""`CompositeTools`: one catalogue over keyed sources (concurrent, in source order, duplicates dropped and logged,
unreachable keys reported, all-down raises), and `call` routed to the source that offered the name, refetching the
catalogue once for a name it does not know."""

import asyncio

import pytest
from ashley import logs
from ashley.inference.model import ToolResult
from ashley.tools.composite import CompositeTools
from ashley.tools.tools import Catalogue, Tools, ToolsUnavailable
from conversations_support import events
from search_contract_support import Stub, call, run


def names(c: Catalogue) -> list[str]:
    return [s.name for s in c.specs]


def make(**sources: Tools) -> CompositeTools:
    return CompositeTools(dict(sources))


def test_the_new_catalogue_field_defaults_to_nothing_unreachable() -> None:
    assert Catalogue((), None).unreachable == ()


def test_specs_are_concatenated_in_source_order() -> None:
    c = run(make(house=Stub("h", ("lights", "fans")), web=Stub("w", ("search_web",)),
                 places=Stub("p", ("find_places",))).catalogue())
    assert names(c) == ["lights", "fans", "search_web", "find_places"]
    assert c.unreachable == ()


def test_mapping_order_not_key_name_sets_source_order() -> None:
    c = run(make(places=Stub("p", ("find_places",)), house=Stub("h", ("lights",))).catalogue())
    assert names(c) == ["find_places", "lights"]


def test_instructions_join_the_reachable_non_empty_ones_with_a_blank_line() -> None:
    c = run(make(a=Stub("a", ("x",), "first"), b=Stub("b", ("y",), None), c=Stub("c", ("z",), ""),
                 d=Stub("d", ("w",), "last"), e=Stub("e", ("v",), "gone", down=True)).catalogue())
    assert c.instructions == "first\n\nlast"


def test_no_instructions_anywhere_is_none() -> None:
    assert run(make(a=Stub("a", ("x",)), b=Stub("b", ("y",), "")).catalogue()).instructions is None


def test_unreachable_sources_are_named_by_key_in_source_order_and_the_rest_still_answer() -> None:
    c = run(make(house=Stub("h", ("lights",), down=True), web=Stub("w", ("search_web",)),
                 places=Stub("p", ("find_places",), down=True)).catalogue())
    assert c.unreachable == ("house", "places")
    assert names(c) == ["search_web"]


def test_every_source_down_raises_tools_unavailable() -> None:
    async def scenario() -> None:
        with pytest.raises(ToolsUnavailable):
            await make(house=Stub("h", down=True), web=Stub("w", down=True)).catalogue()

    run(scenario())


def test_an_empty_but_reachable_source_is_not_unreachable() -> None:
    c = run(make(house=Stub("h", ()), web=Stub("w", ("search_web",))).catalogue())
    assert c.unreachable == () and names(c) == ["search_web"]


def test_sources_are_asked_concurrently() -> None:
    both = asyncio.Event()
    started = 0

    async def meet() -> None:
        nonlocal started
        started += 1
        if started == 2:
            both.set()
        await asyncio.wait_for(both.wait(), 2)   # a sequential composite never lets the second start

    c = run(make(a=Stub("a", ("x",), gate=meet), b=Stub("b", ("y",), gate=meet)).catalogue())
    assert names(c) == ["x", "y"]


def test_a_duplicate_name_keeps_the_earlier_source_and_is_logged(capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    capsys.readouterr()
    c = run(make(house=Stub("h", ("lights", "search_web")), web=Stub("w", ("search_web", "other"))).catalogue())
    assert names(c) == ["lights", "search_web", "other"]
    (line,) = events(capsys.readouterr().out, "tools.duplicate")
    assert (line["tool"], line["kept"], line["dropped"]) == ("search_web", "house", "web")


def test_a_dropped_duplicate_is_called_on_the_source_that_kept_it() -> None:
    house, web = Stub("h", ("search_web",)), Stub("w", ("search_web",))
    comp = make(house=house, web=web)
    run(comp.catalogue())
    result = run(comp.call(call("search_web", {})))
    assert result == ToolResult("c1", "h:search_web") and web.called == []


def test_no_duplicates_logs_nothing(capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    capsys.readouterr()
    run(make(a=Stub("a", ("x",)), b=Stub("b", ("y",))).catalogue())
    assert events(capsys.readouterr().out, "tools.duplicate") == []


def test_a_call_goes_to_the_source_that_offered_the_name_and_its_result_is_unchanged() -> None:
    house, web = Stub("h", ("lights",)), Stub("w", ("search_web",))
    comp = make(house=house, web=web)
    run(comp.catalogue())
    asked = call("search_web", {"query": "x"}, "id7")
    assert run(comp.call(asked)) == ToolResult("id7", "w:search_web")
    assert web.called == [asked] and house.called == []


def test_a_call_before_any_catalogue_fetches_it_once_then_routes() -> None:
    house, web = Stub("h", ("lights",)), Stub("w", ("search_web",))
    comp = make(house=house, web=web)
    assert run(comp.call(call("search_web", {}))) == ToolResult("c1", "w:search_web")
    assert (house.catalogues, web.catalogues) == (1, 1)


def test_a_known_name_does_not_refetch_the_catalogue() -> None:
    web = Stub("w", ("search_web",))
    comp = make(web=web)

    async def scenario() -> None:
        await comp.catalogue()
        await comp.call(call("search_web", {}))
        await comp.call(call("search_web", {}, "c2"))

    run(scenario())
    assert web.catalogues == 1


def test_an_unknown_name_refetches_once_and_is_an_error_result(capsys: pytest.CaptureFixture[str]) -> None:
    house = Stub("h", ("lights",))
    comp = make(house=house)
    run(comp.catalogue())
    logs.setup()
    capsys.readouterr()
    result = run(comp.call(call("no_such_tool", {"q": "zqARG"}, "id9")))
    assert result == ToolResult("id9", "no tool named no_such_tool", is_error=True)
    assert house.catalogues == 2 and house.called == []
    out = capsys.readouterr().out
    (line,) = events(out, "tools.call")
    assert (line["tool"], line["outcome"]) == ("no_such_tool", "unknown_tool")
    assert "zqARG" not in out


def test_a_tool_that_appeared_since_the_catalogue_is_found_by_the_refetch() -> None:
    web = Stub("w", ("search_web",))
    comp = make(web=web)
    run(comp.catalogue())
    web.names = ("search_web", "new_tool")
    assert run(comp.call(call("new_tool", {}))) == ToolResult("c1", "w:new_tool")


def test_a_call_never_raises_when_the_refetch_finds_every_source_down() -> None:
    web = Stub("w", ("search_web",))
    comp = make(web=web)
    run(comp.catalogue())
    web.down = True
    result = run(comp.call(call("search_web_2", {})))
    assert result.is_error and result.call_id == "c1"


def test_routing_follows_the_latest_catalogue() -> None:
    a, b = Stub("a", ("x",)), Stub("b", ("y",))
    comp = make(a=a, b=b)
    run(comp.catalogue())
    a.names, b.names = ("y",), ("x",)
    run(comp.catalogue())
    assert run(comp.call(call("x", {}))) == ToolResult("c1", "b:x")

