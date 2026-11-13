"""A connection's settings through the real app: read with the kind's schema, replaced whole under a revision, refused
in the words the route declares, the history, the catalogue the service offers, and who may do any of it."""

from typing import Any

import psycopg
from ashley import services
from ashley.connections.connections import Connections
from ashley.home_assistant.homes import Home, Homes
from ashley.home_assistant.house import ActionInfo, State
from fastapi.testclient import TestClient
from house_double_support import MemoryHouse, state
from oauth_home_support import ORIGIN, Home as People, as_, client as client, google as google, home as home
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from ashley.home_assistant.client import HomeAssistant
import httpx2

LISTS = [{"action": "todo.get_items", "ids": ["todo.inbox"]}]


def add(client: TestClient, home: People, kind: str = "home_assistant", person: int | None = None) -> int:
    async def make() -> int:
        found = await services.get(Connections).add(home.household, kind, "", "http://ha.test:8123", "token", home.alana,
                                                    "person" if person else None)
        return found.id

    return client.portal.call(make) if client.portal else 0


def settings_url(cid: int, tail: str = "settings") -> str:
    return f"/api/connections/{cid}/{tail}"


def put(client: TestClient, cid: int, revision: int, values: list[dict[str, Any]], headers: dict[str, str] | None = ORIGIN):
    return client.put(settings_url(cid), json={"revision": revision, "values": values}, headers=headers)


def test_a_connection_never_set_answers_the_kind_s_schema_and_revision_zero(client: TestClient, home: People) -> None:
    cid = add(client, home)
    got = client.get(settings_url(cid))
    assert got.status_code == 200, got.text
    body = got.json()
    assert (body["connection_id"], body["kind"], body["revision"], body["values"]) == (cid, "home_assistant", 0, [])
    assert body["updated_at"] is None and body["updated_by"] is None
    assert [s["key"] for s in body["settings"]] == ["household_reads", "service_reads", "reads", "consequential_entities", "glance_calendars"]
    first = body["settings"][0]
    assert first["field"] == {"type": "entity_per_action", "for_actions": ["todo.get_items"], "domains": ["todo"]}
    assert first["decides"] == "taint" and {s["decides"] for s in body["settings"]} == {"taint", "tier", "read", "plain"}


def test_a_write_is_stored_whole_and_answered_with_who_wrote_it(client: TestClient, home: People) -> None:
    cid = add(client, home)
    wrote = put(client, cid, 0, [{"key": "household_reads", "per_action": LISTS}, {"key": "reads", "ids": ["script.a"]}])
    assert wrote.status_code == 200, wrote.text
    body = wrote.json()
    assert body["revision"] == 1 and body["updated_by"]["id"] == home.alana and body["updated_at"]
    again = client.get(settings_url(cid)).json()
    assert again["values"] == body["values"] == [
        {"key": "household_reads", "ids": [], "per_action": LISTS}, {"key": "reads", "ids": ["script.a"], "per_action": []}]


def test_a_write_at_a_stale_revision_is_409_version_conflict_and_changes_nothing(client: TestClient, home: People) -> None:
    cid = add(client, home)
    assert put(client, cid, 0, [{"key": "reads", "ids": ["script.a"]}]).status_code == 200
    stale = put(client, cid, 0, [{"key": "reads", "ids": ["script.z"]}])
    assert stale.status_code == 409 and stale.json()["code"] == "version_conflict"
    assert client.get(settings_url(cid)).json()["values"][0]["ids"] == ["script.a"]


def test_a_value_the_kind_does_not_take_is_422_naming_the_key_and_the_reason(client: TestClient, home: People) -> None:
    cid = add(client, home)
    refused = put(client, cid, 0, [{"key": "reads", "ids": ["not an id"]}])
    assert refused.status_code == 422
    assert (refused.json()["key"], refused.json()["reason"]) == ("reads", "bad_id")
    unknown = put(client, cid, 0, [{"key": "colour", "ids": ["a.b"]}])
    assert (unknown.status_code, unknown.json()["reason"]) == (422, "unknown_key")
    assert client.get(settings_url(cid)).json()["revision"] == 0


def test_a_request_outside_its_schema_is_422_and_stores_nothing(client: TestClient, home: People) -> None:
    cid = add(client, home)
    assert client.put(settings_url(cid), json={"revision": -1, "values": []}, headers=ORIGIN).status_code == 422
    assert client.put(settings_url(cid), json={"values": []}, headers=ORIGIN).status_code == 422
    assert client.get(settings_url(cid)).json()["revision"] == 0


def test_a_write_from_another_site_or_with_no_session_is_refused(client: TestClient, home: People) -> None:
    cid = add(client, home)
    assert put(client, cid, 0, [], headers={"origin": "https://elsewhere.test"}).status_code == 403
    client.cookies.clear()
    assert put(client, cid, 0, []).status_code == 401
    assert client.get(settings_url(cid)).status_code == 401


def test_another_person_of_the_household_may_write_the_settings(client: TestClient, home: People) -> None:
    cid = add(client, home)
    as_(client, home.sam_token)
    wrote = put(client, cid, 0, [{"key": "reads", "ids": ["script.a"]}])
    assert wrote.status_code == 200 and wrote.json()["updated_by"]["id"] == home.sam


def test_a_connection_of_another_household_or_a_kind_with_no_settings_is_404(client: TestClient, home: People, db_url: str) -> None:
    with psycopg.connect(db_url, autocommit=True) as conn:
        other = conn.execute("INSERT INTO households (name) VALUES ('other') RETURNING id").fetchone()
        assert other is not None
        theirs = conn.execute("INSERT INTO connections (household_id, kind, label, base_url, secret) "
                              "VALUES (%s, 'home_assistant', '', 'http://x.test', '\\x00') RETURNING id", (other[0],)).fetchone()
    assert theirs is not None
    for tail in ("settings", "settings/history", "catalogue"):
        assert client.get(settings_url(theirs[0], tail)).status_code == 404, tail
    assert put(client, theirs[0], 0, [{"key": "reads", "ids": ["script.a"]}]).status_code == 404
    sure = add(client, home, "sure")
    assert client.get(settings_url(sure)).status_code == 404
    assert put(client, sure, 0, []).status_code == 404
    assert client.get(settings_url(0)).status_code == 404


def test_the_history_lists_each_key_changed_newest_first_and_pages(client: TestClient, home: People) -> None:
    cid = add(client, home)
    put(client, cid, 0, [{"key": "reads", "ids": ["script.a"]}])
    put(client, cid, 1, [{"key": "reads", "ids": ["script.a"]}, {"key": "service_reads", "ids": ["weather.x"]}])
    put(client, cid, 2, [{"key": "service_reads", "ids": ["weather.x"]}])
    got = client.get(settings_url(cid, "settings/history")).json()
    assert [c["key"] for c in got["changes"]] == ["reads", "service_reads", "reads"] and got["next_before"] is None
    assert got["changes"][0]["edited_by"]["id"] == home.alana
    page = client.get(settings_url(cid, "settings/history"), params={"limit": 2}).json()
    assert len(page["changes"]) == 2 and page["next_before"] == page["changes"][-1]["id"]
    rest = client.get(settings_url(cid, "settings/history"), params={"limit": 2, "before": page["next_before"]}).json()
    assert [c["key"] for c in rest["changes"]] == ["reads"] and rest["next_before"] is None
    assert client.get(settings_url(cid, "settings/history"), params={"limit": 0}).status_code == 422


class OneHouse(Homes):
    """Every household reaches the one house given."""

    def __init__(self, house: MemoryHouse) -> None:
        self._house = house

    async def of(self, household_id: int) -> Home | None:
        return Home(household_id, HomeAssistant(httpx2.AsyncClient(base_url="http://ha.test:8123")), self._house)

    async def check(self, base_url: str, token: str) -> None:
        raise AssertionError("not checked here")


def reach(things: list[State], down: bool = False) -> None:
    house = MemoryHouse(things=things, down=down)
    house.catalogue = [ActionInfo("script.travel", "t", {}, "only"), ActionInfo("weather.get_forecasts", "w", {}, "only"),
                       ActionInfo("light.turn_on", "l", {}, "none")]
    services.register(Homes, OneHouse(house))


def test_the_catalogue_is_the_house_s_things_and_actions_narrowed_to_the_domains_asked(client: TestClient, home: People) -> None:
    cid = add(client, home)
    reach([state("todo.inbox", "Inbox", "1"), state("switch.relay", "Relay", "off", device_class="outlet"),
           state("light.den", "Den", "off")])
    everything = client.get(settings_url(cid, "catalogue")).json()
    assert {e["entity_id"] for e in everything["entities"]} == {"todo.inbox", "switch.relay", "light.den"}
    assert {a["name"] for a in everything["actions"]} == {"script.travel", "weather.get_forecasts", "light.turn_on"}
    relay = next(e for e in everything["entities"] if e["entity_id"] == "switch.relay")
    assert relay == {"entity_id": "switch.relay", "name": "Relay", "domain": "switch", "device_class": "outlet"}
    flags = {a["name"]: a["looks_up_only"] for a in everything["actions"]}
    assert flags == {"script.travel": True, "weather.get_forecasts": True, "light.turn_on": False}
    narrowed = client.get(settings_url(cid, "catalogue"), params=[("domains", "todo"), ("domains", "script")]).json()
    assert [e["entity_id"] for e in narrowed["entities"]] == ["todo.inbox"]
    assert [a["name"] for a in narrowed["actions"]] == ["script.travel"]
    assert narrowed["read_at"]


def test_a_house_that_does_not_answer_is_503_unavailable_not_an_empty_catalogue(client: TestClient, home: People) -> None:
    cid = add(client, home)
    reach([state("todo.inbox", "Inbox", "1")], down=True)
    down = client.get(settings_url(cid, "catalogue"))
    assert (down.status_code, down.json()["code"]) == (503, "unavailable")


def test_a_domain_that_is_not_a_domain_is_422(client: TestClient, home: People) -> None:
    cid = add(client, home)
    assert client.get(settings_url(cid, "catalogue"), params={"domains": "Not A Domain!"}).status_code == 422


def test_the_kinds_listing_says_which_kinds_have_settings(client: TestClient) -> None:
    offered = {k["name"]: k["has_settings"] for k in client.get("/api/connections").json()["offered"]}
    assert offered["home_assistant"] is True and offered["sure"] is False
