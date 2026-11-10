"""`Reading`: a Tools with only the tools of its source whose spec says `reads`; the rest are neither listed nor
callable, whatever name they are asked for by."""

import random

import pytest
from ashley.tools.reading import Reading
from ashley.tools.tools import ToolsUnavailable
from reminders_look_blind_support import CHANGES, READS, Listed, called, mixed, names, offered, spec
import asyncio


def test_it_lists_the_tools_that_read_in_the_sources_order_and_no_other() -> None:
    assert offered(Reading(mixed())) == ["look_up", "balance"]


def test_a_listed_spec_is_the_sources_own() -> None:
    source = mixed()
    got = asyncio.run(Reading(source).catalogue())
    assert got.specs == tuple(s for s in source.specs if s.reads)


def test_the_sources_guidance_and_unreachable_sources_are_still_reported() -> None:
    source = Listed(mixed().specs, unreachable=("house",), instructions="use the tools")
    got = asyncio.run(Reading(source).catalogue())
    assert got.instructions == "use the tools" and got.unreachable == ("house",)


@pytest.mark.parametrize("name", CHANGES)
def test_a_tool_that_changes_something_is_refused_and_never_reaches_the_source(name: str) -> None:
    source = mixed()
    got = called(Reading(source), name)
    assert got.is_error
    assert source.called == []


@pytest.mark.parametrize("name", CHANGES)
def test_it_is_refused_after_the_catalogue_was_read_too(name: str) -> None:
    source = mixed()
    reading = Reading(source)
    offered(reading)
    assert called(reading, name).is_error and source.called == []


@pytest.mark.parametrize("name", READS)
def test_a_tool_that_reads_goes_to_the_source_and_its_answer_comes_back(name: str) -> None:
    source = mixed()
    got = called(Reading(source), name)
    assert not got.is_error and got.content == f"done:{name}" and got.call_id == "c1"
    assert source.called == [name]


@pytest.mark.parametrize("name", ["", "nope", "LOOK_UP", "look_up ", " look_up", "look_up\x00", "look-up", "*"])
def test_a_name_the_source_never_offered_is_refused(name: str) -> None:
    source = mixed()
    assert called(Reading(source), name).is_error and source.called == []


def test_a_name_is_matched_whole_never_by_its_tail_after_a_domain_prefix() -> None:
    source = Listed((spec("HassTurnOn", False), spec("light__HassTurnOn", True), spec("look_up", True)))
    reading = Reading(source)
    assert offered(reading) == ["light__HassTurnOn", "look_up"]
    assert called(reading, "HassTurnOn").is_error and source.called == []
    assert not called(reading, "light__HassTurnOn").is_error and source.called == ["light__HassTurnOn"]


def test_a_read_named_like_a_change_by_its_tail_is_not_a_way_to_call_the_change() -> None:
    source = Listed((spec("lamp_on", False), spec("lamp_on_status", True)))
    assert called(Reading(source), "lamp_on").is_error and source.called == []


def test_a_source_that_cannot_be_listed_makes_the_catalogue_unavailable_as_it_does() -> None:
    with pytest.raises(ToolsUnavailable):
        asyncio.run(Reading(Listed(mixed().specs, down=True)).catalogue())


@pytest.mark.parametrize("name", [*READS, *CHANGES])
def test_with_the_source_unlistable_nothing_is_called(name: str) -> None:
    source = Listed(mixed().specs, down=True)
    got = called(Reading(source), name)
    assert got.is_error and source.called == []


def test_a_source_with_nothing_that_reads_offers_nothing_and_calls_nothing() -> None:
    source = Listed(tuple(spec(n, False) for n in CHANGES))
    reading = Reading(source)
    assert offered(reading) == [] and called(reading, "lamp_on").is_error and source.called == []


def test_an_empty_source_offers_nothing() -> None:
    assert offered(Reading(Listed(()))) == []


def test_it_follows_the_source_as_it_changes() -> None:
    source = Listed((spec("look_up", True),))
    reading = Reading(source)
    assert offered(reading) == ["look_up"]
    source.specs = (spec("look_up", False), spec("balance", True))
    assert offered(reading) == ["balance"]
    assert called(reading, "look_up").is_error and not called(reading, "balance").is_error


@pytest.mark.parametrize("seed", range(8))
def test_for_any_mix_what_is_listed_is_exactly_what_can_be_called(seed: int) -> None:
    rng = random.Random(seed)
    pool = [spec(f"tool_{i}", rng.random() < 0.5) for i in range(12)]
    source = Listed(tuple(pool))
    reading = Reading(source)
    listed = offered(reading)
    assert listed == [s.name for s in pool if s.reads]
    for s in pool:
        got = called(reading, s.name)
        assert got.is_error is (s.name not in listed)
    assert source.called == listed
    assert names(asyncio.run(reading.catalogue())) == listed
