"""`PlacesTools`: `find_places` over Photon, biased to the house. The request (bias rounded to `bias_decimals`), the
ranking by great-circle distance from the UNROUNDED home, the cap, skipped features, the address and distance
formatting (from a captured Photon body), the home cached for `home_ttl_s` with a failure never cached, every error's
reason, and logs free of the query and coordinates."""

import copy
import json
import time
from typing import Any
from urllib.parse import parse_qs

import pytest
from ashley import logs
from ashley.home_assistant.zone import Coordinates, HomeUnknown
from ashley.tools.places import PlacesTools
from conversations_support import events
from search_contract_support import (BROKEN_BODIES, CONFIG, MARK, PHOTON, Web, call, cfg, connect_web, json_web, miles, run,
                            timeout_web)

NEEDS_QUERY = "find_places needs a query"
DID_NOT_ANSWER = "places search did not answer"
HOME_UNKNOWN = "the house's location is unknown"
ROUND_HOME = Coordinates(40.0, -105.0)
FEATURES: list[dict[str, Any]] = PHOTON["features"]


class Home:
    """The `home` callable: answers `coordinates`, or raises HomeUnknown while `down`; counts its calls."""

    def __init__(self, coordinates: Coordinates = ROUND_HOME, down: bool = False) -> None:
        self.coordinates, self.down, self.calls = coordinates, down, 0

    async def __call__(self) -> Coordinates:
        self.calls += 1
        if self.down:
            raise HomeUnknown("no location")
        return self.coordinates


def body(features: list[dict[str, Any]]) -> dict[str, Any]:
    return {**copy.deepcopy(PHOTON), "features": copy.deepcopy(features)}


def feature(lat: float, lon: float, name: str | None = "Spot", **props: Any) -> dict[str, Any]:
    """A Photon feature at a chosen point, its properties from the captured first feature."""
    out = copy.deepcopy(FEATURES[0])
    out["geometry"]["coordinates"] = [lon, lat]
    out["properties"] = {**out["properties"], "name": name, **props}
    return out


def find(web: Web, arguments: dict[str, object] | None = None, home: Home | None = None, config: Any = CONFIG) -> Any:
    tool = PlacesTools(web.client(), config, home or Home())
    return run(tool.call(call("find_places", {"query": "Target"} if arguments is None else arguments)))


def places(web: Web, arguments: dict[str, object] | None = None, home: Home | None = None,
           config: Any = CONFIG) -> list[dict[str, Any]]:
    result = find(web, arguments, home, config)
    assert not result.is_error, result.content
    return json.loads(result.content)["places"]


def test_the_captured_body_has_the_shape_these_tests_rely_on() -> None:
    assert len(FEATURES) == 15
    assert FEATURES[0]["properties"]["name"] == "Target" and FEATURES[0]["properties"]["osm_value"] == "department_store"
    assert [round(miles(40.0, -105.0, *f["geometry"]["coordinates"][::-1]), 1) for f in FEATURES[:3]] == [2.8, 5.9, 8.9]


def test_the_catalogue_is_one_tool_with_a_query_parameter() -> None:
    c = run(PlacesTools(Web().client(), CONFIG, Home()).catalogue())
    (tool,) = c.specs
    assert tool.name == "find_places"
    assert tool.parameters == {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}
    assert "mile" in tool.description.lower() and "nearest" in tool.description.lower()
    assert c.instructions is None and c.unreachable == ()


def test_the_request_asks_photon_for_the_query_biased_to_the_rounded_home() -> None:
    web = json_web(PHOTON)
    places(web, {"query": "Target"}, Home(Coordinates(39.73421, -104.99317)))
    (request,) = web.requests
    assert request.method == "GET"
    assert f"{request.url.scheme}://{request.url.host}{request.url.path}" == "https://photon.test/api/"
    q = parse_qs(request.url.query.decode())
    assert set(q) == {"q", "lat", "lon", "limit"}
    assert q["q"] == ["Target"] and q["limit"] == ["15"]
    assert float(q["lat"][0]) == 39.73 and float(q["lon"][0]) == -104.99
    assert request.extensions["timeout"]["read"] == CONFIG.timeout_s


@pytest.mark.parametrize(("decimals", "lat", "lon"), [(1, 39.7, -105.0), (3, 39.734, -104.993)])
def test_the_bias_is_rounded_to_bias_decimals(decimals: int, lat: float, lon: float) -> None:
    web = json_web(PHOTON)
    places(web, home=Home(Coordinates(39.73421, -104.99317)), config=cfg(bias_decimals=decimals))
    q = parse_qs(web.requests[0].url.query.decode())
    assert (float(q["lat"][0]), float(q["lon"][0])) == (lat, lon)


def test_limit_is_places_fetched() -> None:
    web = json_web(PHOTON)
    places(web, config=cfg(places_fetched=9))
    assert parse_qs(web.requests[0].url.query.decode())["limit"] == ["9"]


def test_the_nearest_come_first_with_name_kind_address_and_distance() -> None:
    web = json_web(body(list(reversed(FEATURES))))
    out = places(web)
    assert out == [
        {"name": "Target", "kind": "department_store", "address": "14451 Orchard Parkway, Westminster, CO", "distance_mi": 2.8},
        {"name": "Target", "kind": "supermarket", "address": "1001 East 120th Avenue, Thornton, CO", "distance_mi": 5.9},
        {"name": "Target", "kind": "department_store", "address": "10445 Reed Street, Westminster, CO", "distance_mi": 8.9},
    ]


def test_photons_own_order_is_not_trusted() -> None:
    near, far = feature(40.01, -105.0, "Near"), feature(40.2, -105.0, "Far")
    out = places(json_web(body([far, near])))
    assert [p["name"] for p in out] == ["Near", "Far"]


def test_ranking_and_distance_use_the_unrounded_home_not_the_rounded_bias() -> None:
    home = Coordinates(40.0049, -105.0049)   # the 2-decimal bias is 40.00, -105.00: 0.0049 degrees south
    north, south = feature(home.latitude + 0.0290, home.longitude, "North"), feature(home.latitude - 0.0300, home.longitude, "South")
    out = places(json_web(body([south, north])), home=Home(home))
    assert [p["name"] for p in out] == ["North", "South"], "from the rounded bias, South would be nearer"
    assert out[0]["distance_mi"] == round(miles(home.latitude, home.longitude, home.latitude + 0.0290, home.longitude), 1)
    assert out[1]["distance_mi"] == round(miles(home.latitude, home.longitude, home.latitude - 0.0300, home.longitude), 1)


def test_distance_is_rounded_to_a_tenth_of_a_mile() -> None:
    for p in places(json_web(PHOTON)):
        assert p["distance_mi"] == round(p["distance_mi"], 1)
    spot = feature(40.0 + 0.02, -105.0)
    (only,) = places(json_web(body([spot])))
    assert only["distance_mi"] == round(miles(40.0, -105.0, 40.02, -105.0), 1) == 1.4


@pytest.mark.parametrize(("cap", "count"), [(1, 1), (3, 3), (6, 6), (15, 15), (40, 15)])
def test_at_most_places_results_come_back(cap: int, count: int) -> None:
    assert len(places(json_web(PHOTON), config=cfg(places_results=cap))) == count


def test_features_without_a_name_or_coordinates_are_skipped_before_the_cap() -> None:
    nameless = copy.deepcopy(FEATURES[0])
    del nameless["properties"]["name"]
    blank = copy.deepcopy(FEATURES[0])
    blank["properties"]["name"] = ""
    no_geometry = copy.deepcopy(FEATURES[1])
    del no_geometry["geometry"]
    no_coordinates = copy.deepcopy(FEATURES[1])
    no_coordinates["geometry"]["coordinates"] = []
    out = places(json_web(body([nameless, blank, no_geometry, no_coordinates, *FEATURES[2:]])), config=cfg(places_results=2))
    assert [p["distance_mi"] for p in out] == [8.9, 9.7]


def test_the_address_is_housenumber_street_then_city_then_state_with_the_parts_that_exist() -> None:
    cases = [
        (dict(housenumber="12", street="Main Street", city="Boulder", state="CO"), "12 Main Street, Boulder, CO"),
        (dict(housenumber=None, street="Main Street", city="Boulder", state="CO"), "Main Street, Boulder, CO"),
        (dict(housenumber=None, street="Main Street", city=None, state=None), "Main Street"),
        (dict(housenumber=None, street=None, city="Boulder", state=None), "Boulder"),
        (dict(housenumber=None, street=None, city=None, state="CO"), "CO"),
    ]
    for props, address in cases:
        spot = feature(40.01, -105.0, **props)
        for key in [k for k, v in props.items() if v is None]:
            del spot["properties"][key]
        assert places(json_web(body([spot])))[0]["address"] == address


def test_a_place_with_no_address_parts_has_no_address_key() -> None:
    spot = feature(40.01, -105.0)
    for key in ("housenumber", "street", "city", "state"):
        del spot["properties"][key]
    (only,) = places(json_web(body([spot])))
    assert set(only) == {"name", "kind", "distance_mi"}


def test_no_features_is_ok_and_empty(capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    capsys.readouterr()
    assert places(json_web(body([]))) == []
    (line,) = events(capsys.readouterr().out, "tools.call")
    assert (line["tool"], line["outcome"], line["results"]) == ("find_places", "ok", "0")


def test_an_ok_call_logs_name_outcome_count_and_duration(capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    capsys.readouterr()
    places(json_web(PHOTON))
    (line,) = events(capsys.readouterr().out, "tools.call")
    assert (line["tool"], line["outcome"], line["results"]) == ("find_places", "ok", "3")
    assert line["duration_ms"].isdigit()


@pytest.mark.parametrize("arguments", [{}, {"query": ""}, {"query": " \t"}, {"query": 3}, {"query": None}, {"q": "Target"}])
def test_a_missing_blank_or_non_string_query_is_an_error_and_asks_nothing(arguments: dict[str, object],
                                                                          capsys: pytest.CaptureFixture[str]) -> None:
    web = json_web(PHOTON)
    logs.setup()
    capsys.readouterr()
    result = find(web, arguments)
    assert result.is_error and result.content == NEEDS_QUERY
    assert web.requests == []
    (line,) = events(capsys.readouterr().out, "tools.call")
    assert (line["tool"], line["outcome"]) == ("find_places", "error")


@pytest.mark.parametrize("make", [timeout_web, connect_web, *[
    (lambda k=k: Web(BROKEN_BODIES[k])) for k in BROKEN_BODIES],
    lambda: json_web({"features": "none"}), lambda: json_web({"type": "FeatureCollection"})])
def test_every_failure_to_answer_is_unavailable_with_one_reason(make: Any, capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    capsys.readouterr()
    result = find(make(), {"query": f"{MARK}"})
    assert result.is_error and result.content == DID_NOT_ANSWER
    (line,) = events(capsys.readouterr().out, "tools.call")
    assert (line["tool"], line["outcome"]) == ("find_places", "unavailable")


def test_an_unknown_home_is_unavailable_with_its_own_reason_and_asks_photon_nothing(
        capsys: pytest.CaptureFixture[str]) -> None:
    web = json_web(PHOTON)
    logs.setup()
    capsys.readouterr()
    result = find(web, home=Home(down=True))
    assert result.is_error and result.content == HOME_UNKNOWN and web.requests == []
    (line,) = events(capsys.readouterr().out, "tools.call")
    assert (line["tool"], line["outcome"]) == ("find_places", "unavailable")


def test_a_name_other_than_find_places_is_unknown_and_asks_nothing(capsys: pytest.CaptureFixture[str]) -> None:
    web, home = json_web(PHOTON), Home()
    logs.setup()
    capsys.readouterr()
    result = run(PlacesTools(web.client(), CONFIG, home).call(call("search_web", {"query": MARK})))
    assert result.is_error and MARK not in result.content and web.requests == []
    (line,) = events(capsys.readouterr().out, "tools.call")
    assert (line["tool"], line["outcome"]) == ("search_web", "unknown_tool")


def test_the_call_id_is_the_asked_one() -> None:
    tool = PlacesTools(json_web(PHOTON).client(), CONFIG, Home())
    assert run(tool.call(call("find_places", {"query": "x"}, "id-42"))).call_id == "id-42"


class Clock:
    """`time.time` and `time.monotonic` moved forward by `skew` seconds (a few, so no loop timer is reached)."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.skew = 0.0
        real_time, real_monotonic = time.time, time.monotonic
        monkeypatch.setattr(time, "time", lambda: real_time() + self.skew)
        monkeypatch.setattr(time, "monotonic", lambda: real_monotonic() + self.skew)


def test_a_known_home_is_asked_once_per_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    clock, home, web = Clock(monkeypatch), Home(), json_web(PHOTON)
    tool = PlacesTools(web.client(), cfg(home_ttl_s=10), home)

    async def ask() -> None:
        assert not (await tool.call(call("find_places", {"query": "Target"}))).is_error

    run(ask())
    run(ask())
    assert home.calls == 1, "the second call within the ttl reuses the home"
    clock.skew = 5
    run(ask())
    assert home.calls == 1
    clock.skew = 11
    run(ask())
    assert home.calls == 2, "past the ttl the home is read again"
    assert len(web.requests) == 4


def test_a_home_failure_is_not_cached() -> None:
    home, web = Home(down=True), json_web(PHOTON)
    tool = PlacesTools(web.client(), CONFIG, home)

    async def scenario() -> None:
        assert (await tool.call(call("find_places", {"query": "x"}))).content == HOME_UNKNOWN
        assert (await tool.call(call("find_places", {"query": "x"}))).content == HOME_UNKNOWN
        assert home.calls == 2, "a failure is asked again at once"
        home.down = False
        assert not (await tool.call(call("find_places", {"query": "x"}))).is_error

    run(scenario())
    assert home.calls == 3


def test_a_failure_after_a_success_does_not_discard_the_cached_home() -> None:
    home, web = Home(), json_web(PHOTON)
    tool = PlacesTools(web.client(), CONFIG, home)

    async def scenario() -> None:
        await tool.call(call("find_places", {"query": "x"}))
        web.answer = BROKEN_BODIES["server_error"]
        assert (await tool.call(call("find_places", {"query": "x"}))).content == DID_NOT_ANSWER

    run(scenario())
    assert home.calls == 1


def test_no_query_coordinate_name_address_or_url_reaches_a_log_line(capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    capsys.readouterr()
    home = Coordinates(39.73421, -104.99317)
    runs = [(json_web(PHOTON), Home(home)), (json_web(body([])), Home(home)), (timeout_web(), Home(home)),
            (connect_web(), Home(home)), (json_web(PHOTON), Home(home, down=True)),
            *[(Web(r), Home(home)) for r in BROKEN_BODIES.values()]]
    reasons = [find(web, {"query": f"{MARK} pharmacy"}, h).content for web, h in runs]
    reasons.append(find(json_web(PHOTON), {"query": " "}, Home(home)).content)
    out = capsys.readouterr().out
    assert len(events(out, "tools.call")) == len(reasons) == 13, "control: every call was logged"
    for leaked in (MARK, "pharmacy", "39.73", "104.99", "-105", "photon.test", "https://", "Orchard", "Westminster",
                   "Target"):
        assert leaked not in out
    assert all(MARK not in r and "39.73" not in r for r in reasons)
