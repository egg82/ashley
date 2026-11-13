"""The catalogue's layers and what a call costs under them (`catalogue_merge`, `catalogue.PricedCatalogue`): the fetch
replaces the snapshot, a person's field wins and every other field follows upstream, a change equal to upstream's is
not stored, unknown is never $0 (no price, a 0/0 listing nobody marked free, a usage part with no price), every price
names its layer, and a model listed without tool calls is refused for tools."""

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from ashley.inference.catalogue import PricedCatalogue
from ashley.inference.catalogue_merge import Override, delta, merged, pricing, upstream
from ashley.inference.catalogue_model import Catalogue, FieldName, ModelFields, Provider, Tier
from ashley.inference.model import Usage
from catalogue_support import PLAIN, flat

D = Decimal
AT = datetime(2026, 11, 13, tzinfo=UTC)
MILLION_IN = Usage(1_000_000, 0)


def listed(fields: ModelFields, provider: str = "p", model: str = "m") -> Catalogue:
    return Catalogue({provider: Provider("P", None, {model: fields})})


def override(field: FieldName, value: object, provider: str = "p", model: str = "m", by: int | None = 7) -> Override:
    return Override(provider, model, field, value, by, AT)


def priced(fields: ModelFields | None, *overrides: Override, layer: str = "fetch") -> PricedCatalogue:
    catalogue = Catalogue({}) if fields is None else listed(fields)
    return PricedCatalogue(merged(catalogue, "fetch" if layer == "fetch" else "snapshot", overrides), PLAIN)


# --- which upstream layer is in force ----------------------------------------------------------------------------

def test_the_fetch_replaces_the_snapshot_whole_and_the_snapshot_stands_alone_before_one() -> None:
    snapshot, fetched = listed(flat("1"), model="old"), listed(flat("2"), model="new")
    assert upstream(snapshot, fetched) == (fetched, "fetch")
    assert upstream(snapshot, None) == (snapshot, "snapshot")
    assert upstream(None, None) == (Catalogue({}), None)
    catalogue, layer = upstream(snapshot, fetched)
    assert set(merged(catalogue, layer, ()).listings) == {("p", "new")}, "a model gone upstream is gone"


# --- overrides over upstream -------------------------------------------------------------------------------------

def test_a_persons_field_wins_and_every_other_field_follows_upstream_as_it_changes() -> None:
    mine = override("input_usd_per_mtok", D("9"))
    before = merged(listed(flat("1", "2")), "fetch", [mine]).listings[("p", "m")]
    after = merged(listed(flat("1", "5")), "fetch", [mine]).listings[("p", "m")]
    assert (before.fields.input_usd_per_mtok, before.fields.output_usd_per_mtok) == (D("9"), D("2"))
    assert (after.fields.input_usd_per_mtok, after.fields.output_usd_per_mtok) == (D("9"), D("5"))
    assert after.default is not None and after.default.input_usd_per_mtok == D("1"), "upstream's value is kept beside"
    assert after.overrides == {"input_usd_per_mtok": mine} and after.overrides["input_usd_per_mtok"].set_by == 7


def test_a_model_only_a_person_names_is_listed_with_no_default_and_its_provider_by_id() -> None:
    added = merged(Catalogue({}), "fetch", [override("name", "Mine", "local", "qwen")])
    listing = added.listings[("local", "qwen")]
    assert listing.default is None and listing.layer is None and listing.fields.name == "Mine"
    assert added.providers["local"].name == "local"


def test_a_persons_price_replaces_upstreams_tiers() -> None:
    tiered = replace(flat("1"), tiers=(Tier(100, D("8"), D("8"), None, None),))
    assert merged(listed(tiered), "fetch", ()).listings[("p", "m")].fields.tiers != ()
    assert merged(listed(tiered), "fetch", [override("output_usd_per_mtok", D("3"))]).listings[("p", "m")].fields.tiers == ()
    assert merged(listed(tiered), "fetch", [override("name", "x")]).listings[("p", "m")].fields.tiers != ()


# --- what a change stores ----------------------------------------------------------------------------------------

def test_a_change_stores_only_what_differs_from_upstream_and_deletes_what_matches() -> None:
    default = flat("3", "15")
    stored, deleted = delta(default, {"input_usd_per_mtok": D("4"), "output_usd_per_mtok": D("15.0")}, [])
    assert stored == {"input_usd_per_mtok": D("4")} and deleted == {"output_usd_per_mtok"}


def test_a_reset_deletes_and_a_persons_flag_set_false_deletes_it() -> None:
    stored, deleted = delta(flat(), {"free": False, "hidden": True}, ["name"])
    assert stored == {"hidden": True} and deleted == {"free", "name"}


def test_on_a_model_upstream_does_not_list_every_set_field_is_stored() -> None:
    stored, deleted = delta(None, {"name": "Mine", "tool_call": False}, [])
    assert stored == {"name": "Mine", "tool_call": False} and deleted == set()


# --- pricing -----------------------------------------------------------------------------------------------------

def test_no_listing_or_no_price_is_unpriced_and_costs_nothing_known() -> None:
    assert pricing(None).status == "unpriced"
    for book in (priced(None), priced(ModelFields(name="m", tool_call=True))):
        assert book.pricing("p", "m").status == "unpriced"
        assert book.cost_usd("p", "m", MILLION_IN) is None


def test_a_listing_of_zero_is_listed_zero_and_records_no_cost_until_a_person_marks_it_free() -> None:
    zero = flat("0", "0", "0", "0")
    book = priced(zero)
    assert (book.pricing("p", "m").status, book.pricing("p", "m").source) == ("listed_zero", "fetch")
    assert book.cost_usd("p", "m", MILLION_IN) is None
    marked = priced(zero, override("free", True))
    assert (marked.pricing("p", "m").status, marked.pricing("p", "m").source) == ("free", "override")
    assert marked.cost_usd("p", "m", MILLION_IN) == D(0)


def test_a_zero_base_with_a_priced_tier_is_priced_not_listed_zero() -> None:
    tiered = replace(flat("0", "0", None, None), tiers=(Tier(10, D("1"), D("1"), None, None),))
    assert priced(tiered).pricing("p", "m").status == "priced"


def test_every_price_names_its_layer() -> None:
    assert priced(flat(), layer="snapshot").pricing("p", "m").source == "snapshot"
    assert priced(flat()).pricing("p", "m").source == "fetch"
    assert priced(flat(), override("cache_read_usd_per_mtok", D("1"))).pricing("p", "m").source == "override"
    assert priced(flat(), override("name", "x")).pricing("p", "m").source == "fetch", "a name is not a price"


def test_a_call_costs_its_tokens_at_their_prices_exactly() -> None:
    usage = Usage(input_tokens=1000, output_tokens=500, cache_read_tokens=200, cache_write_tokens=100)
    assert priced(flat()).cost_usd("p", "m", usage) == D("0.010935")


@pytest.mark.parametrize(("usage", "missing"), [(Usage(10, 10, cache_read_tokens=5), "read"),
                                                (Usage(10, 10, cache_write_tokens=5), "write")])
def test_a_usage_part_the_model_lists_no_price_for_records_no_cost(usage: Usage, missing: str) -> None:
    fields = flat(read=None) if missing == "read" else flat(write=None)
    assert priced(fields).cost_usd("p", "m", usage) is None
    assert priced(fields).cost_usd("p", "m", Usage(10, 10)) is not None, "control: the same model prices tokens"


@pytest.mark.parametrize("usage", [Usage(0, 0, audio_ms=5000), Usage(0, 0, characters=40)])
def test_audio_or_characters_are_never_priced_by_token_prices(usage: Usage) -> None:
    assert priced(flat()).cost_usd("p", "m", usage) is None


def test_a_local_provider_costs_zero_for_any_usage_and_says_so() -> None:
    book = priced(None)
    assert book.pricing("here", "anything").status == "local"
    assert book.cost_usd("here", "anything", Usage(0, 0, audio_ms=5000)) == D(0)


def test_a_prompt_longer_than_a_tier_pays_that_tier_and_one_at_its_bound_pays_the_base() -> None:
    tiered = replace(flat("1", "0", "0", "0"), tiers=(Tier(100, D("5"), D("0"), D("0"), D("0")),
                                                      Tier(200, D("9"), D("0"), D("0"), D("0"))))
    book = priced(tiered)
    assert book.cost_usd("p", "m", Usage(100, 0)) == D(100).scaleb(-6)
    assert book.cost_usd("p", "m", Usage(101, 0)) == D(505).scaleb(-6)
    assert book.cost_usd("p", "m", Usage(51, 0, cache_read_tokens=50)) == D(255).scaleb(-6), "cache tokens count"
    assert book.cost_usd("p", "m", Usage(201, 0)) == D(1809).scaleb(-6)


def test_a_route_provider_name_is_priced_under_the_catalogue_provider_it_maps_to() -> None:
    book = PricedCatalogue(merged(listed(flat("2"), provider="google"), "fetch", ()),
                           replace(PLAIN, providers={"gemini": "google"}))
    assert book.cost_usd("gemini", "m", MILLION_IN) == D(2)
    assert book.cost_usd("google", "m", MILLION_IN) == D(2)
    assert book.cost_usd("openai", "m", MILLION_IN) is None


# --- tools -------------------------------------------------------------------------------------------------------

def test_only_a_model_listed_without_tool_calls_is_refused_for_tools() -> None:
    assert priced(flat(tool_call=False)).refuses_tools("p", "m")
    assert not priced(flat(tool_call=True)).refuses_tools("p", "m")
    assert not priced(flat(tool_call=None)).refuses_tools("p", "m")
    assert not priced(None).refuses_tools("p", "m"), "a model not listed is not refused"
    assert not priced(flat(tool_call=False), override("tool_call", True)).refuses_tools("p", "m")
    assert priced(flat(), override("tool_call", False)).refuses_tools("p", "m")
