"""The shipped image data: the routes load against the real image makers (so a typo in their params fails here, not at
start-up), every routed model has a price, a provider that cannot draw is rejected for the task, and the household limit
parses strictly."""

import json
from datetime import date
from decimal import Decimal
from importlib import resources

import httpx2
import pytest
from ashley.inference import image_quota, prices, routes
from ashley.inference.fastembed_embedder import FastEmbedder
from ashley.inference.gemini_image import GeminiImageMaker
from ashley.inference.model import Usage
from ashley.inference.openai_image import OpenAIImageMaker
from ashley.inference.routes import parse


def makers() -> dict[str, GeminiImageMaker | OpenAIImageMaker]:
    client = httpx2.AsyncClient()
    return {"gemini_image": GeminiImageMaker("gemini_image", client), "openai_image": OpenAIImageMaker("openai_image", client)}


def test_the_shipped_image_routes_load_against_the_real_makers_and_are_priced() -> None:
    loaded = routes.load(makers())
    image = loaded.for_task("image")
    assert [r.provider for r in image] == ["gemini_image", "openai_image"]
    book = prices.load()
    for route in image:
        assert book.cost_usd(route.provider, route.model, Usage(1000, 1000), date(2026, 11, 3)) is not None, route.model


def test_an_image_route_naming_a_provider_that_cannot_draw_is_rejected() -> None:
    data = {"cooldown_s": 1, "tasks": {**_shipped(), "image": [{"provider": "fastembed", "model": "m", "timeout_s": 1}]}}
    with pytest.raises(ValueError, match="cannot do task image"):
        parse(data, {"fastembed": FastEmbedder("fastembed", "/nowhere")})


def _shipped() -> dict[str, object]:
    shipped = json.loads(resources.files("ashley.inference").joinpath("routes.json").read_text())
    return dict(shipped["tasks"])


def test_the_cost_of_a_priced_image_call_is_the_token_prices() -> None:
    cost = prices.load().cost_usd("openai_image", "gpt-image-2.5-flare", Usage(12, 196), date(2026, 11, 3))
    assert cost == Decimal("0.00594")


def test_the_limit_ships_and_parses_strictly() -> None:
    assert image_quota.load() == image_quota.ImageLimit(20, 86400)
    bad: list[object] = [None, [], {}, {"max_per_household": 1}, {"max_per_household": 0, "window_s": 1},
                         {"max_per_household": 1, "window_s": True}, {"max_per_household": 1, "window_s": 1, "x": 1}]
    for case in bad:
        with pytest.raises(ValueError):
            image_quota.parse(case)
