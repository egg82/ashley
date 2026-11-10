"""`PlacesTools` against a captured Photon answer (around 40.0, -105.0): the rounded bias it sends, the ranking by
distance from the precise point, how the house's location is read and cached, how it fails and what it logs."""

import asyncio
import json
import re
from dataclasses import replace

import httpx2
import pytest

from ashley import logs
from ashley.home_assistant.zone import Coordinates, HomeUnknown
from ashley.inference.model import ToolCall, ToolResult
from ashley.tools.places import PlacesTools, distance_mi
from ashley.tools.search_config import SearchConfig
from search_support import CONFIG, Fake, call, captured, events, raising, serving

HOUSE = Coordinates(40.004321, -104.998765)   # near the round point the capture was taken around


class Home:
    def __init__(self, fails: int = 0) -> None:
        self.reads = 0
        self._fails = fails

    async def __call__(self) -> Coordinates:
        self.reads += 1
        if self.reads <= self._fails:
            raise HomeUnknown("unreachable")
        return HOUSE


def find(fake: Fake, home: Home | None = None, config: SearchConfig = CONFIG, **arguments: object) -> ToolResult:
    tools = PlacesTools(fake.client(), config, home or Home())
    return asyncio.run(tools.call(call("find_places", **arguments)))


def test_the_catalogue_is_one_places_tool() -> None:
    (spec,) = asyncio.run(PlacesTools(serving({}).client(), CONFIG, Home()).catalogue()).specs
    assert spec.name == "find_places" and spec.parameters["required"] == ["query"]


def test_it_sends_only_the_rounded_point() -> None:
    fake = serving(captured("photon"))
    find(fake, query="Target")
    (request,) = fake.requests
    assert str(request.url).startswith("https://photon.komoot.io/api/?")
    assert dict(request.url.params) == {"q": "Target", "lat": "40.0", "lon": "-105.0", "limit": "15"}
    assert "40.004321" not in str(request.url)


def test_the_nearest_few_come_first_with_kind_address_and_miles() -> None:
    places = json.loads(find(serving(captured("photon")), query="Target").content)["places"]
    assert len(places) == CONFIG.places_results
    assert places[0] == {"name": "Target", "kind": "department_store",
                         "address": "14451 Orchard Parkway, Westminster, CO", "distance_mi": 3.1}
    miles = [p["distance_mi"] for p in places]
    assert miles == sorted(miles)
    every = json.loads(find(serving(captured("photon")), config=replace(CONFIG, places_results=15),
                            query="Target").content)["places"]
    assert len(every) == 15 and [p["distance_mi"] for p in every] == sorted(p["distance_mi"] for p in every)


def test_ranking_is_from_the_precise_point_not_the_rounded_one() -> None:
    body = {"features": [_feature("Far", -105.0, 40.0), _feature("Near", -104.9988, 40.0043)]}
    names = [p["name"] for p in json.loads(find(serving(body), query="x").content)["places"]]
    assert names == ["Near", "Far"]


def test_features_without_a_name_or_a_point_are_skipped_and_parts_omitted() -> None:
    body = {"features": [
        {"type": "Feature", "properties": {"osm_value": "shop"}, "geometry": {"coordinates": [-105, 40]}},
        {"type": "Feature", "properties": {"name": "No point"}},
        {"type": "Feature", "properties": {"name": "Bare"}, "geometry": {"type": "Point", "coordinates": [-105, 40]}},
    ]}
    assert json.loads(find(serving(body), query="x").content) == {"places": [{"name": "Bare", "distance_mi": 0.3}]}


def test_the_house_is_read_once_per_ttl_and_a_failure_is_not_kept() -> None:
    home = Home(fails=1)
    tools = PlacesTools(serving(captured("photon")).client(), CONFIG, home)

    async def scenario() -> list[ToolResult]:
        return [await tools.call(call("find_places", query="Target")) for _ in range(3)]

    first, second, third = asyncio.run(scenario())
    assert first.is_error and first.content == "the house's location is unknown"
    assert not second.is_error and not third.is_error
    assert home.reads == 2
    expiring = Home()
    tools = PlacesTools(serving(captured("photon")).client(), replace(CONFIG, home_ttl_s=1e-9), expiring)
    asyncio.run(scenario())
    assert expiring.reads == 3


@pytest.mark.parametrize("arguments", [{}, {"query": None}, {"query": ""}])
def test_a_missing_query_is_an_error_and_asks_nothing(arguments: dict[str, object]) -> None:
    fake, home = serving(captured("photon")), Home()
    result = asyncio.run(PlacesTools(fake.client(), CONFIG, home).call(ToolCall("c1", "find_places", arguments)))
    assert result.is_error and result.content == "find_places needs a query"
    assert fake.requests == [] and home.reads == 0


@pytest.mark.parametrize("fake", [
    raising(httpx2.ReadTimeout("slow")), raising(httpx2.ConnectError("refused")), serving({}, 502),
    serving({"type": "FeatureCollection"}), Fake(lambda _: httpx2.Response(200, text="nope")),
])
def test_a_source_that_does_not_answer_is_unavailable(fake: Fake) -> None:
    result = find(fake, query="Target")
    assert result.is_error and result.content == "places search did not answer"


def test_the_log_carries_outcome_and_count_never_the_query_or_place(capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    capsys.readouterr()
    find(serving(captured("photon")), query="PLANTED-QUERY-zq")
    find(serving(captured("photon")), Home(fails=1), query="PLANTED-QUERY-zq")
    out = capsys.readouterr().out
    assert [(e["tool"], e["outcome"], e["results"]) for e in events(out, "tools.call")] == [
        ("find_places", "ok", str(CONFIG.places_results)), ("find_places", "unavailable", "0")]
    fields = re.sub(r"(?m)^ts=\S+ ", "", out)   # a timestamp like 06:03:40.091Z holds "40.0" by chance
    for planted in ("PLANTED-QUERY-zq", "Orchard", "40.0", "-105"):
        assert planted not in fields


def test_distance_is_great_circle_miles() -> None:
    assert distance_mi(Coordinates(40.0, -105.0), Coordinates(40.0, -105.0)) == 0
    assert distance_mi(Coordinates(40.0, -105.0), Coordinates(41.0, -105.0)) == pytest.approx(69.09, abs=0.01)


def _feature(name: str, lon: float, lat: float) -> dict[str, object]:
    return {"type": "Feature", "properties": {"name": name}, "geometry": {"type": "Point", "coordinates": [lon, lat]}}
