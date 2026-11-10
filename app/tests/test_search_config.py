"""The search tunables (`search.json`), SearXNG's address from the env, and the house's location (`zone.home`)."""

import asyncio
import json
from typing import Any

import httpx2
import pytest

from ashley.home_assistant.client import HomeAssistant
from ashley.settings import from_env
from ashley.home_assistant.zone import Coordinates, HomeUnknown, home
from ashley.tools import search_config
from ashley.tools.search_config import SearchConfig

SHIPPED: dict[str, Any] = json.loads(search_config.FILE.read_text())


def test_the_shipped_config_loads() -> None:
    assert search_config.load() == SearchConfig(**SHIPPED)


@pytest.mark.parametrize(("raw", "read"), [(" https://search.test/ ", "https://search.test"), (None, "")])
def test_the_search_address_is_the_envs(raw: str | None, read: str) -> None:
    env = {"DATABASE_URL": "postgresql://x"} | ({} if raw is None else {"SEARXNG_URL": raw})
    assert from_env(env).searxng_url == read


@pytest.mark.parametrize("change", [
    {"web_results": None}, {"extra": 1}, {"timeout_s": 0}, {"places_results": -1}, {"bias_decimals": 1.5},
    {"snippet_chars": True}, {"home_ttl_s": "1"}, {"photon_url": ""}, {"photon_url": 3},
    {"searxng_url": "https://search.test"},
])
def test_a_bad_config_is_refused(change: dict[str, Any]) -> None:
    data = {**SHIPPED, **change}
    data = {k: v for k, v in data.items() if v is not None}
    with pytest.raises(ValueError):
        search_config.parse(data)


def test_a_config_that_is_not_an_object_is_refused() -> None:
    with pytest.raises(ValueError):
        search_config.parse([])


def _ha(answer: httpx2.Response | Exception) -> HomeAssistant:
    def handle(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/api/states/zone.home"
        if isinstance(answer, Exception):
            raise answer
        return answer
    return HomeAssistant(httpx2.AsyncClient(base_url="http://ha.test", transport=httpx2.MockTransport(handle)))


def test_the_house_is_zone_homes_coordinates() -> None:
    body = {"entity_id": "zone.home", "state": "2", "attributes": {"latitude": 40.0, "longitude": -105, "radius": 100}}
    assert asyncio.run(home(_ha(httpx2.Response(200, json=body)))) == Coordinates(40.0, -105.0)


@pytest.mark.parametrize("answer", [
    httpx2.ConnectError("refused"), httpx2.ReadTimeout("slow"), httpx2.Response(401, json={}),
    httpx2.Response(200, text="nope"), httpx2.Response(200, json={"attributes": {"latitude": 40.0}}),
    httpx2.Response(200, json={"attributes": {"latitude": "40", "longitude": -105}}),
    httpx2.Response(200, json={"attributes": {"latitude": True, "longitude": -105}}),
])
def test_an_unreadable_house_is_unknown(answer: httpx2.Response | Exception) -> None:
    with pytest.raises(HomeUnknown):
        asyncio.run(home(_ha(answer)))
