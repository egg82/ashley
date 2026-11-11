"""The deployment gate: a deployment-kind connection is changed only by an admin of the first household (403
`admin_only` for any other member, 404 for another household, as today), a household's own connection stays any
member's, and `can_change` says which is which."""

from collections.abc import Generator

import pytest
from admin_role_blind_support import (ORIGIN, World, add_connection, app_mode as app_mode, as_, codes, idp as idp,
                                      session_for, set_admin, world as world)
from ashley import services
from ashley.sure.client import Sure
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from fastapi.testclient import TestClient
from money_support import BASE, KEY, FakeSure

ANTHROPIC = "https://api.anthropic.com"
HA = "http://ha.test:8123"
NEW_KEY = {"api_key": "sk-new"}


@pytest.fixture
def sure() -> Generator[FakeSure]:
    fake = FakeSure()
    yield fake
    services.unregister(Sure)


def who(client: TestClient, db_url: str, world: World, person: int) -> None:
    as_(client, session_for(db_url, world, person))


def held(client: TestClient, world: World) -> tuple[int, int]:
    """(an Anthropic key, a Home Assistant) of the first household, both deployment kinds in this registry."""
    return (add_connection(client, world.home, "anthropic", world.alana, ANTHROPIC),
            add_connection(client, world.home, "home_assistant", world.alana, HA, "token"))


def post_key(client: TestClient, label: str = "") -> tuple[int, str | None]:
    return codes(client.post("/api/connections", json={"kind": "anthropic", "label": label, **NEW_KEY}, headers=ORIGIN))


def test_gate_a_non_admin_first_household_member_s_post_of_a_deployment_kind_is_403_admin_only(
        app_mode: TestClient, db_url: str, world: World) -> None:
    who(app_mode, db_url, world, world.sam)
    assert post_key(app_mode) == (403, "admin_only")
    assert app_mode.get("/api/connections").json()["connections"] == []


def test_gate_a_non_admin_s_put_of_a_deployment_kind_is_403_admin_only(app_mode: TestClient, db_url: str,
                                                                       world: World) -> None:
    key, _ = held(app_mode, world)
    who(app_mode, db_url, world, world.sam)
    assert codes(app_mode.put(f"/api/connections/{key}", json=NEW_KEY, headers=ORIGIN)) == (403, "admin_only")


def test_gate_a_non_admin_s_patch_of_a_deployment_kind_is_403_admin_only(app_mode: TestClient, db_url: str,
                                                                         world: World) -> None:
    key, _ = held(app_mode, world)
    who(app_mode, db_url, world, world.sam)
    assert codes(app_mode.patch(f"/api/connections/{key}", json={"label": "renamed"}, headers=ORIGIN)) == (403, "admin_only")


def test_gate_a_non_admin_s_delete_of_a_deployment_kind_is_403_admin_only_and_keeps_it(
        app_mode: TestClient, db_url: str, world: World) -> None:
    key, _ = held(app_mode, world)
    who(app_mode, db_url, world, world.sam)
    assert codes(app_mode.delete(f"/api/connections/{key}", headers=ORIGIN)) == (403, "admin_only")
    assert [c["id"] for c in app_mode.get("/api/connections").json()["connections"]] == [key, key + 1]


def test_gate_a_non_admin_s_settings_put_on_a_deployment_kind_is_403_admin_only(app_mode: TestClient, db_url: str,
                                                                                world: World) -> None:
    _, ha = held(app_mode, world)
    who(app_mode, db_url, world, world.sam)
    got = app_mode.put(f"/api/connections/{ha}/settings", json={"revision": 0, "values": []}, headers=ORIGIN)
    assert codes(got) == (403, "admin_only")
    assert app_mode.get(f"/api/connections/{ha}/settings").json()["revision"] == 0


def test_gate_a_non_admin_s_resource_change_on_a_deployment_kind_is_403_admin_only(app_mode: TestClient, db_url: str,
                                                                                   world: World) -> None:
    google = add_connection(app_mode, world.home, "google", world.alana, "https://gmail.test", "refresh")
    who(app_mode, db_url, world, world.sam)
    got = app_mode.patch(f"/api/connections/{google}/resources/alana@gmail.test", json={"shared": True}, headers=ORIGIN)
    assert codes(got) == (403, "admin_only")


def test_gate_an_admin_adds_replaces_renames_and_removes_a_deployment_kind(app_mode: TestClient, db_url: str,
                                                                          world: World) -> None:
    set_admin(db_url, world.sam)
    who(app_mode, db_url, world, world.sam)
    made = app_mode.post("/api/connections", json={"kind": "anthropic", "label": "", **NEW_KEY}, headers=ORIGIN)
    assert made.status_code == 201, made.text
    cid = made.json()["id"]
    assert app_mode.put(f"/api/connections/{cid}", json={"api_key": "sk-rotated"}, headers=ORIGIN).status_code == 200
    assert app_mode.patch(f"/api/connections/{cid}", json={"label": "spare"}, headers=ORIGIN).status_code == 200
    assert app_mode.delete(f"/api/connections/{cid}", headers=ORIGIN).status_code == 204
    assert app_mode.get("/api/connections").json()["connections"] == []


def test_gate_an_admin_writes_the_settings_of_a_deployment_kind(app_mode: TestClient, db_url: str, world: World) -> None:
    _, ha = held(app_mode, world)
    set_admin(db_url, world.sam)
    who(app_mode, db_url, world, world.sam)
    got = app_mode.put(f"/api/connections/{ha}/settings", json={"revision": 0, "values": []}, headers=ORIGIN)
    assert got.status_code == 200, got.text


def test_gate_an_admin_s_resource_change_is_not_refused_as_admin_only(app_mode: TestClient, db_url: str,
                                                                     world: World) -> None:
    google = add_connection(app_mode, world.home, "google", world.alana, "https://gmail.test", "refresh")
    set_admin(db_url, world.sam)
    who(app_mode, db_url, world, world.sam)
    got = app_mode.patch(f"/api/connections/{google}/resources/alana@gmail.test", json={"shared": True}, headers=ORIGIN)
    assert codes(got)[1] != "admin_only" and got.status_code != 403


def test_gate_another_household_gets_404_not_403_even_as_an_admin_there(app_mode: TestClient, db_url: str,
                                                                        world: World) -> None:
    key, ha = held(app_mode, world)
    set_admin(db_url, world.kim)
    who(app_mode, db_url, world, world.kim)
    assert codes(app_mode.post("/api/connections", json={"kind": "anthropic", "label": "", **NEW_KEY},
                               headers=ORIGIN))[0] == 404
    assert app_mode.put(f"/api/connections/{key}", json=NEW_KEY, headers=ORIGIN).status_code == 404
    assert app_mode.patch(f"/api/connections/{key}", json={"label": "x"}, headers=ORIGIN).status_code == 404
    assert app_mode.delete(f"/api/connections/{key}", headers=ORIGIN).status_code == 404
    assert app_mode.put(f"/api/connections/{ha}/settings", json={"revision": 0, "values": []},
                        headers=ORIGIN).status_code == 404


def test_gate_another_household_non_admin_gets_404_not_403(app_mode: TestClient, db_url: str, world: World) -> None:
    key, _ = held(app_mode, world)
    who(app_mode, db_url, world, world.kim)
    assert app_mode.delete(f"/api/connections/{key}", headers=ORIGIN).status_code == 404
    assert codes(app_mode.post("/api/connections", json={"kind": "anthropic", "label": "", **NEW_KEY},
                               headers=ORIGIN))[0] == 404


def test_gate_a_household_connection_is_still_any_member_s_to_change(app_mode: TestClient, db_url: str, world: World,
                                                                    sure: FakeSure) -> None:
    services.register(Sure, sure.client())
    who(app_mode, db_url, world, world.sam)
    made = app_mode.post("/api/connections", json={"kind": "sure", "label": "", "base_url": BASE, "api_key": KEY},
                         headers=ORIGIN)
    assert made.status_code == 201, made.text
    cid = made.json()["id"]
    who(app_mode, db_url, world, world.ivy)
    assert app_mode.put(f"/api/connections/{cid}", json={"base_url": BASE, "api_key": KEY}, headers=ORIGIN).status_code == 200
    assert app_mode.patch(f"/api/connections/{cid}", json={"label": "books"}, headers=ORIGIN).status_code == 200
    assert app_mode.delete(f"/api/connections/{cid}", headers=ORIGIN).status_code == 204


def test_gate_can_change_is_false_for_a_deployment_kind_a_non_admin_sees(app_mode: TestClient, db_url: str,
                                                                         world: World, sure: FakeSure) -> None:
    services.register(Sure, sure.client())
    key, _ = held(app_mode, world)
    sure_id = add_connection(app_mode, world.home, "sure", world.alana, BASE, KEY)
    who(app_mode, db_url, world, world.sam)
    seen = {c["id"]: c["can_change"] for c in app_mode.get("/api/connections").json()["connections"]}
    assert seen[key] is False and seen[sure_id] is True


def test_gate_can_change_is_true_everywhere_for_an_admin(app_mode: TestClient, db_url: str, world: World,
                                                         sure: FakeSure) -> None:
    services.register(Sure, sure.client())
    key, ha = held(app_mode, world)
    sure_id = add_connection(app_mode, world.home, "sure", world.alana, BASE, KEY)
    set_admin(db_url, world.sam)
    who(app_mode, db_url, world, world.sam)
    seen = {c["id"]: c["can_change"] for c in app_mode.get("/api/connections").json()["connections"]}
    assert seen == {key: True, ha: True, sure_id: True}


def test_gate_a_revoked_admin_loses_the_gate_at_once(app_mode: TestClient, db_url: str, world: World) -> None:
    set_admin(db_url, world.sam)
    set_admin(db_url, world.alana)
    who(app_mode, db_url, world, world.sam)
    assert app_mode.post("/api/connections", json={"kind": "anthropic", "label": "", **NEW_KEY},
                         headers=ORIGIN).status_code == 201
    set_admin(db_url, world.sam, False)
    assert post_key(app_mode, "second") == (403, "admin_only")
