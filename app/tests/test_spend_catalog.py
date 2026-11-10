"""The provider catalog and the budgets file: the shipped ones load, the budgets ship empty, and a file that cannot work
is refused by name."""

import json
from importlib import resources

import pytest
from ashley.inference import prices, spend_catalog


def shipped(name: str) -> object:
    return json.loads(resources.files("ashley.inference").joinpath(name).read_text())


def test_the_shipped_catalog_loads_with_every_priced_provider_and_no_budget() -> None:
    catalog = spend_catalog.load()
    assert catalog.monthly_usd == {}
    priced = set(prices.load().by_model)
    assert priced <= set(catalog.providers)
    assert {"anthropic", "openai", "gemini", "gemini_image", "openai_image", "elevenlabs"} <= set(catalog.providers)


def test_a_paid_provider_with_no_balance_read_carries_its_reason_and_page() -> None:
    catalog = spend_catalog.load()
    for name in ("anthropic", "openai", "gemini", "gemini_image", "openai_image"):
        info = catalog.providers[name]
        assert info.kind == "paid" and info.why_unknown and (info.source or "").startswith("https://")


def test_a_budget_is_a_positive_number_for_a_paid_provider_in_the_catalog() -> None:
    providers = shipped("providers.json")
    assert spend_catalog.parse(providers, {"monthly_usd": {"anthropic": 25, "openai": 7.5}}).monthly_usd == {
        "anthropic": 25.0, "openai": 7.5}


@pytest.mark.parametrize("budgets", [
    {"monthly_usd": {"anthropic": 0}}, {"monthly_usd": {"anthropic": -1}}, {"monthly_usd": {"anthropic": "5"}},
    {"monthly_usd": {"anthropic": True}}, {"monthly_usd": {"anthropic": float("inf")}},
    {"monthly_usd": {"antropic": 5}}, {"monthly_usd": {"fastembed": 5}}, {}, [], {"monthly_usd": []}])
def test_a_budget_that_cannot_work_is_refused(budgets: object) -> None:
    with pytest.raises(ValueError):
        spend_catalog.parse(shipped("providers.json"), budgets)


@pytest.mark.parametrize("entry", [{}, {"label": "X"}, {"label": "X", "kind": "free"}, {"label": " ", "kind": "paid"},
                                   {"label": "X", "kind": "paid", "extra": 1}, {"label": "X", "kind": "paid", "source": ""}])
def test_a_provider_entry_that_cannot_work_is_refused(entry: object) -> None:
    with pytest.raises(ValueError):
        spend_catalog.parse({"x": entry}, {"monthly_usd": {}})
