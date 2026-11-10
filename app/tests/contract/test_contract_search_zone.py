"""`zone.home`: the house's coordinates from HA's `zone.home` state; `HomeUnknown` for any transport error, non-2xx or
missing/non-numeric latitude/longitude; coordinates and the token never logged. The success body is shaped from HA's
documented zone state (not captured); the failure bodies are the captured 401 and 404."""

from typing import Any

import httpx2
import pytest
from ashley import logs
from ashley.home_assistant.client import HomeAssistant
from ashley.home_assistant.zone import Coordinates, HomeUnknown, home
from ha_support import CAPTURES, HA_TOKEN
from search_contract_support import Web, connect_web, json_web, run, timeout_web

ATTRIBUTES: dict[str, Any] = {"latitude": 39.73421, "longitude": -104.99317, "radius": 100.0, "passive": False,
                              "persons": [], "editable": True, "icon": "mdi:home", "friendly_name": "Home"}


def state(**attributes: Any) -> dict[str, Any]:
    merged = {k: v for k, v in {**ATTRIBUTES, **attributes}.items() if v is not ...}
    return {"entity_id": "zone.home", "state": "0", "attributes": merged,
            "last_changed": "2026-10-25T18:00:00+00:00", "context": {"id": "01JZ", "parent_id": None, "user_id": None}}


def handle(web: Web) -> HomeAssistant:
    return HomeAssistant(httpx2.AsyncClient(transport=httpx2.MockTransport(web.handle), base_url="http://ha.test:8123",
                                            headers={"Authorization": f"Bearer {HA_TOKEN}"}))


def unknown(web: Web) -> None:
    async def scenario() -> None:
        with pytest.raises(HomeUnknown):
            await home(handle(web))

    run(scenario())


def test_the_house_is_the_zone_homes_latitude_and_longitude() -> None:
    web = json_web(state())
    assert run(home(handle(web))) == Coordinates(39.73421, -104.99317)
    (request,) = web.requests
    assert request.method == "GET" and request.url.path == "/api/states/zone.home"
    assert request.headers["Authorization"] == f"Bearer {HA_TOKEN}"


def test_integer_coordinates_are_numbers_too() -> None:
    assert run(home(handle(json_web(state(latitude=40, longitude=-105))))) == Coordinates(40.0, -105.0)


def test_coordinates_are_a_frozen_pair() -> None:
    c = Coordinates(1.5, 2.5)
    assert (c.latitude, c.longitude) == (1.5, 2.5)
    with pytest.raises(AttributeError):
        setattr(c, "latitude", 3.0)


@pytest.mark.parametrize("web", [
    timeout_web(), connect_web(),
    Web(httpx2.Response(401, text=(CAPTURES / "unauth.json").read_text())),
    Web(httpx2.Response(404, text=(CAPTURES / "state-missing.json").read_text())),
    Web(httpx2.Response(500, text="500 Internal Server Error")),
    Web(httpx2.Response(200, text="<html>bad gateway</html>")),
    Web(httpx2.Response(200, json=[])),
    Web(httpx2.Response(200, json={"state": "0"})),
    Web(httpx2.Response(200, json=state(latitude=...))),
    Web(httpx2.Response(200, json=state(longitude=...))),
    Web(httpx2.Response(200, json=state(latitude=None))),
    Web(httpx2.Response(200, json=state(longitude="west"))),
    Web(httpx2.Response(200, json=state(latitude="abc"))),
    Web(httpx2.Response(200, json=state(latitude=[40.0]))),
], ids=["timeout", "connect", "401", "404", "500", "html", "list", "no_attributes", "no_latitude", "no_longitude",
        "null_latitude", "text_longitude", "text_latitude", "list_latitude"])
def test_anything_but_two_numbers_is_home_unknown(web: Web) -> None:
    unknown(web)


def test_a_valid_body_behind_an_error_status_is_home_unknown() -> None:
    unknown(json_web(state(), status=503))


def test_no_coordinate_or_token_reaches_a_log_line(capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    capsys.readouterr()
    run(home(handle(json_web(state()))))
    for web in (timeout_web(), json_web(state(longitude="west")), json_web(state(), status=500)):
        unknown(web)
    out = capsys.readouterr().out
    for leaked in ("39.73", "104.99", HA_TOKEN):
        assert leaked not in out
