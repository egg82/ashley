"""A variant's `core` is parsed like its other lists, reported unmet like its `sources`, and leaves a cut without one
offering every source."""

import json
from collections.abc import Generator
from dataclasses import replace

import pytest
from ashley.channels import cut, on_demand
from ashley.evals import variant
from ashley.inference.model import ToolSpec
from ashley.tools.tools import Catalogue


@pytest.fixture(autouse=True)
def clean() -> Generator[None]:
    cut.install(cut.NO_CUT)
    yield
    cut.install(cut.NO_CUT)


def parsed(**data: object) -> variant.Variant:
    return variant.parse(json.dumps({"name": "core-a", **data}))


def catalogue() -> Catalogue:
    specs = tuple(ToolSpec(n, n, {"type": "object"}) for n in ("lights", "remind", "mail_send"))
    loader = ToolSpec(on_demand.LOADER, "load", {"type": "object"})
    return Catalogue((*specs, loader), "a\n\nb\n\nc", sources=("everyday", "reminders", "mail"),
                     owners={"lights": "everyday", "remind": "reminders", "mail_send": "mail"},
                     guidance={"everyday": "a", "reminders": "b", "mail": "c"})


def test_core_is_a_set_of_source_names_and_absent_means_none() -> None:
    assert parsed(core=["everyday", "reminders"]).cut.core == frozenset({"everyday", "reminders"})
    assert parsed(core=[]).cut.core == frozenset()
    assert parsed().cut.core is None and parsed(sources=["mail"]).cut.core is None


def test_a_core_changes_the_label_digest_and_the_other_lists_are_untouched() -> None:
    assert parsed(core=["everyday"]).label != parsed(core=["reminders"]).label != parsed().label
    got = parsed(core=["everyday"], sources=["mail"], tools=["lights"])
    assert (got.cut.sources, got.cut.tools, got.cut.examples, got.cut.sections) == (
        frozenset({"mail"}), frozenset({"lights"}), frozenset(), frozenset())


@pytest.mark.parametrize("core", ["everyday", [1], [""], {"a": 1}])
def test_a_core_that_is_not_a_list_of_names_is_refused(core: object) -> None:
    with pytest.raises(ValueError, match="'core' is a list"):
        parsed(core=core)


def test_a_core_name_no_turn_held_fails_the_run_naming_it() -> None:
    variant.install(parsed(core=["everyday", "evryday"]))
    cut.thinned(catalogue())
    with pytest.raises(ValueError, match="evryday"):
        variant.finish()
    assert cut.unmet() == ("evryday",)


def test_with_a_core_the_catalogue_loses_the_others_tools_and_instructions_until_they_are_loaded() -> None:
    variant.install(parsed(core=["everyday"]))
    first = cut.thinned(catalogue())
    assert [s.name for s in first.specs] == ["lights", on_demand.LOADER]
    assert first.instructions == "a" and list(first.owners) == ["lights"]
    later = cut.thinned(catalogue(), frozenset({"mail"}))
    assert [s.name for s in later.specs] == ["lights", on_demand.LOADER, "mail_send"]
    assert later.instructions == "a\n\nc"


def test_a_catalogue_without_the_loader_is_left_as_it_is_whatever_the_core() -> None:
    variant.install(parsed(core=["everyday"]))
    plain = replace(catalogue(), specs=catalogue().specs[:-1])
    assert cut.thinned(plain) is plain


def test_no_core_is_the_catalogue_itself() -> None:
    assert cut.thinned(catalogue()) == catalogue()
