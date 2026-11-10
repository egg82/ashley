"""`GET /api/connections/{id}/catalogue`: the picker's entities and actions from that household's own house."""

from conn_settings_blind_support import People, as_, connect_ha
from fastapi.testclient import TestClient


def test_it_lists_the_houses_entities_filtered_by_domain(client: TestClient) -> None:
    cid = connect_ha(client)
    got = client.get(f"/api/connections/{cid}/catalogue", params={"domains": "todo"})
    assert got.status_code == 200, got.text
    ids = {e["id"] for e in got.json()["entities"]}
    assert ids == {"todo.inbox", "todo.family", "todo.to_do_list"}


def test_several_domains_and_no_filter(client: TestClient) -> None:
    cid = connect_ha(client)
    both = client.get(f"/api/connections/{cid}/catalogue", params={"domains": "todo,switch"}).json()["entities"]
    assert {"todo.inbox", "switch.lamp"} <= {e["id"] for e in both}
    assert not any(e["id"].startswith("light.") for e in both)
    one = client.get(f"/api/connections/{cid}/catalogue", params={"domains": "switch"}).json()["entities"]
    assert {e["id"] for e in one} == {"switch.lamp", "switch.fan_relay"}


def test_it_lists_actions(client: TestClient) -> None:
    cid = connect_ha(client)
    got = client.get(f"/api/connections/{cid}/catalogue", params={"domains": "script"}).json()
    assert {"script.find_person", "script.where"} <= {a["name"] for a in got["actions"]}


def test_another_household_cannot_read_it(client: TestClient, people: People) -> None:
    cid = connect_ha(client)
    as_(client, people, "kim")
    assert client.get(f"/api/connections/{cid}/catalogue", params={"domains": "todo"}).status_code == 404
    as_(client, people, None)
    assert client.get(f"/api/connections/{cid}/catalogue", params={"domains": "todo"}).status_code == 401
