"""models.dev's `api.json` read into a catalogue (`ashley.inference.models_dev`): the captured excerpt reads with exact
prices and prompt-length tiers, a price never turns a missing part into 0, and an entry it cannot read is left out and
counted while the rest stand."""

import copy
import json
from collections.abc import Callable
from decimal import Decimal
from typing import Any

import pytest
from ashley.inference import models_dev
from ashley.inference.catalogue_model import (Catalogue, Tier, catalogue_from_json, catalogue_to_json)
from catalogue_support import CAPTURED

D = Decimal


def raw() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(CAPTURED.read_text())
    return data


def model(data: dict[str, Any], provider: str = "anthropic", name: str = "claude-haiku-5-5") -> dict[str, Any]:
    found: dict[str, Any] = data[provider]["models"][name]
    return found


def test_the_captured_list_reads_every_provider_and_model_with_none_skipped() -> None:
    read = models_dev.parse(raw())
    assert read.skipped == 0
    assert set(read.catalogue.providers) == {"anthropic", "openai", "google", "unorouter", "the-grid-ai"}
    assert read.catalogue.model_count() == sum(len(p["models"]) for p in raw().values())


def test_a_model_reads_its_name_capabilities_limits_and_exact_prices() -> None:
    haiku = models_dev.parse(raw()).catalogue.providers["anthropic"].models["claude-haiku-5-5"]
    assert (haiku.name, haiku.tool_call, haiku.structured_output) == ("Claude Haiku 5.5", True, True)
    assert (haiku.context_tokens, haiku.max_output_tokens) == (1_000_000, 128_000)
    assert (haiku.input_usd_per_mtok, haiku.output_usd_per_mtok, haiku.cache_read_usd_per_mtok,
            haiku.cache_write_usd_per_mtok) == (D("0.1"), D("0.5"), D("0.01"), D("0.125"))
    assert str(haiku.cache_read_usd_per_mtok) == "0.01"
    assert haiku.tiers == (Tier(100_000, D("0.5"), D("2.5"), D("0.05"), D("0.625")),)


def test_a_price_part_the_list_leaves_out_is_unknown_not_zero() -> None:
    argon = models_dev.parse(raw()).catalogue.providers["google"].models["gemini-4-argon"]
    assert argon.cache_write_usd_per_mtok is None and argon.input_usd_per_mtok == D("2")


def test_tiers_win_over_the_older_context_over_200k_and_that_alone_is_a_tier_at_200k() -> None:
    data = raw()
    luna = models_dev.parse(data).catalogue.providers["openai"].models["gpt-6-luna"]
    assert [t.above_prompt_tokens for t in luna.tiers] == [272_000]
    del model(data, "openai", "gpt-6-luna")["cost"]["tiers"]
    alone = models_dev.parse(data).catalogue.providers["openai"].models["gpt-6-luna"]
    assert alone.tiers == (Tier(200_000, D("0.2"), D("0.75"), D("0.02"), D("0.25")),)


def test_tiers_are_ordered_by_size_whatever_order_they_are_listed_in() -> None:
    data = raw()
    cost = model(data)["cost"]
    cost["tiers"] = [{**cost["tiers"][0], "tier": {"type": "context", "size": 500_000}}, cost["tiers"][0]]
    tiers = models_dev.parse(data).catalogue.providers["anthropic"].models["claude-haiku-5-5"].tiers
    assert [t.above_prompt_tokens for t in tiers] == [100_000, 500_000]


@pytest.mark.parametrize("tier", [{"type": "time_of_day", "size": 5}, {"type": "context"}, {"type": "context", "size": 0},
                                  "context", None])
def test_a_tier_of_another_kind_leaves_the_whole_price_out(tier: object) -> None:
    data = raw()
    model(data)["cost"]["tiers"][0]["tier"] = tier
    haiku = models_dev.parse(data).catalogue.providers["anthropic"].models["claude-haiku-5-5"]
    assert haiku.input_usd_per_mtok is None and haiku.output_usd_per_mtok is None and haiku.tiers == ()
    assert haiku.tool_call is True, "the model is still listed"


@pytest.mark.parametrize("bad", [-1, "x", True, [1], float("nan")])
def test_a_price_that_is_not_one_leaves_the_price_out(bad: object) -> None:
    data = raw()
    model(data)["cost"]["output"] = bad
    haiku = models_dev.parse(data).catalogue.providers["anthropic"].models["claude-haiku-5-5"]
    assert haiku.input_usd_per_mtok is None and haiku.output_usd_per_mtok is None


def test_a_model_without_a_cost_is_listed_unpriced() -> None:
    grid = models_dev.parse(raw()).catalogue.providers["the-grid-ai"].models["text-standard"]
    assert grid.tool_call is True and grid.input_usd_per_mtok is None and grid.output_usd_per_mtok is None


BREAKS: dict[str, Callable[[dict[str, Any]], object]] = {
    "no name": lambda m: m.pop("name"), "no tool_call": lambda m: m.pop("tool_call"),
    "tool_call not a flag": lambda m: m.update(tool_call="yes"), "empty": lambda m: m.clear()}


@pytest.mark.parametrize("breaks", sorted(BREAKS))
def test_a_model_it_cannot_read_is_left_out_and_counted_and_the_rest_stand(breaks: str) -> None:
    data = raw()
    BREAKS[breaks](model(data))
    read = models_dev.parse(data)
    assert read.skipped == 1
    assert "claude-haiku-5-5" not in read.catalogue.providers["anthropic"].models
    assert "claude-opus-5-5" in read.catalogue.providers["anthropic"].models


def test_a_provider_it_cannot_read_is_left_out_and_counted() -> None:
    data = raw()
    data["broken"] = {"models": {}}
    data["also"] = "nope"
    read = models_dev.parse(data)
    assert read.skipped == 2 and "broken" not in read.catalogue.providers and "anthropic" in read.catalogue.providers


def test_a_provider_api_is_kept_only_as_an_https_url() -> None:
    data = raw()
    data["unorouter"]["api"] = "http://api.unorouter.com/v1"
    providers = models_dev.parse(data).catalogue.providers
    assert providers["unorouter"].api is None
    assert models_dev.parse(raw()).catalogue.providers["unorouter"].api == "https://api.unorouter.com/v1"


@pytest.mark.parametrize("data", [[], "x", None, {}, {"a": "b"}])
def test_a_body_with_no_readable_provider_is_refused(data: object) -> None:
    with pytest.raises(ValueError):
        models_dev.parse(data)


def test_the_stored_form_reads_back_to_the_same_catalogue() -> None:
    catalogue = models_dev.parse(raw()).catalogue
    stored = json.loads(json.dumps(catalogue_to_json(catalogue)))
    assert catalogue_from_json(stored) == catalogue
    assert catalogue_from_json(copy.deepcopy(stored)) != Catalogue({})
