"""A variant's `core` is parsed like its other lists (or is `"all"`), reported unmet like its `sources`, and leaves a cut
without one on the deployed default."""

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


def catalogue(core: frozenset[str] | None = None) -> Catalogue:
    specs = tuple(ToolSpec(n, n, {"type": "object"}) for n in ("lights", "remind", "mail_send"))
    loader = ToolSpec(on_demand.LOADER, "load", {"type": "object"})
    return Catalogue((*specs, loader), "a\n\nb\n\nc", sources=("everyday", "reminders", "mail"),
                     owners={"lights": "everyday", "remind": "reminders", "mail_send": "mail"},
                     guidance={"everyday": "a", "reminders": "b", "mail": "c"}, core=core)


def test_core_is_a_set_of_source_names_and_absent_means_none() -> None:
    assert parsed(core=["everyday", "reminders"]).cut.core == frozenset({"everyday", "reminders"})
    assert parsed(core=[]).cut.core == frozenset()
    assert parsed().cut.core is None and parsed(sources=["mail"]).cut.core is None


def test_core_all_is_every_source_and_is_not_the_deployed_default() -> None:
    assert parsed(core="all").cut.core == cut.ALL != parsed().cut.core
    assert parsed(core="all").label != parsed().label
    assert cut.unmet() == ()
    variant.install(parsed(core="all"))
    assert cut.unmet() == ()


def test_a_core_changes_the_label_digest_and_the_other_lists_are_untouched() -> None:
    assert parsed(core=["everyday"]).label != parsed(core=["reminders"]).label != parsed().label
    got = parsed(core=["everyday"], sources=["mail"], tools=["lights"])
    assert (got.cut.sources, got.cut.tools, got.cut.examples, got.cut.sections) == (
        frozenset({"mail"}), frozenset({"lights"}), frozenset(), frozenset())


@pytest.mark.parametrize("core", ["every", [1], [""], {"a": 1}, None])
def test_a_core_that_is_not_a_list_of_names_is_refused(core: object) -> None:
    with pytest.raises(ValueError, match="'core' is a list"):
        parsed(core=core)


def test_a_core_name_no_turn_held_fails_the_run_naming_it() -> None:
    variant.install(parsed(core=["everyday", "evryday"]))
    on_demand.thinned(catalogue(frozenset({"everyday", "evryday"})))
    with pytest.raises(ValueError, match="evryday"):
        variant.finish()
    assert cut.unmet() == ("evryday",)


def test_with_a_core_the_catalogue_loses_the_others_tools_and_instructions_until_they_are_loaded() -> None:
    variant.install(parsed(core=["everyday"]))
    core = cut.active().core
    assert isinstance(core, frozenset)
    first = on_demand.thinned(catalogue(core))
    assert [s.name for s in first.specs] == ["lights", on_demand.LOADER]
    assert first.instructions == "a" and list(first.owners) == ["lights"]
    later = on_demand.thinned(catalogue(core), frozenset({"mail"}))
    assert [s.name for s in later.specs] == ["lights", on_demand.LOADER, "mail_send"]
    assert later.instructions == "a\n\nc"


def test_a_catalogue_without_the_loader_is_left_as_it_is_whatever_the_core() -> None:
    plain = replace(catalogue(frozenset({"everyday"})), specs=catalogue().specs[:-1])
    assert on_demand.thinned(plain) is plain


def test_a_catalogue_with_no_core_is_the_catalogue_itself() -> None:
    assert on_demand.thinned(catalogue()) == catalogue() == cut.thinned(catalogue())
