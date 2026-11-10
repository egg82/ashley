"""The connection routes addressed by id, through the real app on a real database: `GET /api/connections`,
`POST /api/connections`, `PUT`/`PATCH`/`DELETE /api/connections/{id}`, their status and error codes, the label rule,
and the routes keyed by kind being gone."""

from typing import Any

import pytest
from connections_by_id_blind_support import ORIGIN, URL, Checks, People, age, as_, one, rows, snapshot
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx2 import Response

SECRET = "route-secret-0001"


def post(client: TestClient, kind: str = "multi", label: str = "work", token: str = SECRET,
         base_url: str = URL, **extra: object) -> Response:
    return client.post("/api/connections", json={"kind": kind, "label": label, "base_url": base_url, "token": token,
                                                  **extra}, headers=ORIGIN)


def made(client: TestClient, kind: str = "multi", label: str = "work") -> dict[str, Any]:
    got = post(client, kind, label)
    assert got.status_code == 201
    return got.json()


def listing(client: TestClient) -> dict[str, Any]:
    got = client.get("/api/connections")
    assert got.status_code == 200
    return got.json()


def code(response: Response) -> object:
    return response.json()["code"]


# --- GET ---------------------------------------------------------------------------------------------------------------


def test_the_listing_carries_each_connections_id_and_label_and_each_kinds_most(client: TestClient) -> None:
    a, b = made(client, "multi", "b"), made(client, "multi", "a")
    got = listing(client)
    assert [(c["id"], c["label"]) for c in got["connections"]] == [(b["id"], "a"), (a["id"], "b")]
    assert {o["name"]: o["most"] for o in got["offered"]} == {"multi": 3, "solo": 1, "big": 6, "own": 3,
                                                               "single_own": 1}
    assert [o["name"] for o in got["offered"]] == ["multi", "solo", "big", "own", "single_own"]


def test_the_listing_is_ordered_by_kind_then_label(client: TestClient) -> None:
    for kind, label in (("multi", "b"), ("big", "z"), ("multi", ""), ("big", "a")):
        made(client, kind, label)
    assert [(c["kind"], c["label"]) for c in listing(client)["connections"]] == [
        ("big", "a"), ("big", "z"), ("multi", ""), ("multi", "b")]


def test_a_connection_wire_carries_what_it_always_did(client: TestClient, people: People) -> None:
    got = made(client, "own", "mine")
    assert got["kind"] == "own" and got["label"] == "mine" and got["base_url"] == URL and got["personal"] is True
    assert got["added_by"]["id"] == people.alana
    assert isinstance(got["id"], int) and "added_at" in got and "checked_at" in got


def test_the_secret_is_never_on_the_wire(client: TestClient) -> None:
    for text in (post(client).text, client.get("/api/connections").text):
        assert SECRET not in text


# --- POST --------------------------------------------------------------------------------------------------------------


def test_post_is_201_and_checks_the_service_before_storing(client: TestClient, checks: Checks, db_url: str) -> None:
    got = post(client)
    assert got.status_code == 201 and rows(db_url) == 1
    assert checks.given == [(URL, SECRET)]


def test_a_refusal_is_400_in_the_kinds_words_and_stores_nothing(client: TestClient, checks: Checks, db_url: str) -> None:
    checks.answer = "key_refused"
    got = post(client)
    assert got.status_code == 400 and got.json()["reason"] == "key_refused"
    assert got.json()["detail"] == "multi says key_refused" and rows(db_url) == 0


def test_an_unknown_kind_is_404_not_found(client: TestClient, checks: Checks, db_url: str) -> None:
    got = post(client, kind="jukebox")
    assert got.status_code == 404 and code(got) == "not_found" and rows(db_url) == 0 and checks.given == []


def test_the_other_secret_field_is_422_unsupported(client: TestClient, db_url: str) -> None:
    got = client.post("/api/connections", json={"kind": "multi", "label": "a", "base_url": URL, "api_key": SECRET},
                      headers=ORIGIN)
    assert got.status_code == 422 and code(got) == "unsupported" and rows(db_url) == 0


def test_a_taken_label_is_409_label_taken_and_stores_nothing_more(client: TestClient, db_url: str) -> None:
    made(client, "multi", "work")
    got = post(client, "multi", "work", token="second-secret-0002")
    assert got.status_code == 409 and code(got) == "label_taken" and rows(db_url) == 1


def test_labels_are_exact_over_http(client: TestClient) -> None:
    made(client, "multi", "work")
    assert post(client, "multi", "Work").status_code == 201


def test_the_empty_label_is_allowed_once(client: TestClient) -> None:
    assert post(client, "multi", "").status_code == 201
    got = post(client, "multi", "")
    assert got.status_code == 409 and code(got) == "label_taken"


def test_past_the_kinds_most_is_409_too_many(client: TestClient, db_url: str) -> None:
    for label in ("a", "b", "c"):
        made(client, "multi", label)
    got = post(client, "multi", "d")
    assert got.status_code == 409 and code(got) == "too_many" and rows(db_url) == 3


def test_a_kind_with_most_one_is_409_too_many_on_its_second(client: TestClient, db_url: str) -> None:
    made(client, "solo", "a")
    got = post(client, "solo", "b")
    assert got.status_code == 409 and code(got) == "too_many" and rows(db_url) == 1


def test_a_personal_kinds_limit_is_per_person(client: TestClient, people: People) -> None:
    made(client, "single_own", "a")
    assert post(client, "single_own", "b").status_code == 409
    as_(client, people, "sam")
    assert post(client, "single_own", "a").status_code == 201


def test_a_label_is_stripped_of_surrounding_whitespace(client: TestClient, db_url: str) -> None:
    got = post(client, "multi", "  work \t")
    assert got.status_code == 201 and got.json()["label"] == "work"
    assert one(db_url, "SELECT label FROM connections") == "work"
    assert post(client, "multi", "work").status_code == 409


def test_a_label_of_forty_characters_is_taken_and_forty_one_is_422(client: TestClient, db_url: str) -> None:
    assert post(client, "multi", "x" * 40).status_code == 201
    got = post(client, "multi", "x" * 41)
    assert got.status_code == 422 and rows(db_url) == 1


def test_a_label_of_only_whitespace_is_the_empty_label(client: TestClient) -> None:
    got = post(client, "multi", "   ")
    assert got.status_code == 201 and got.json()["label"] == ""


@pytest.mark.parametrize("body", [{"kind": "multi", "base_url": URL, "token": SECRET},
                                  {"label": "a", "base_url": URL, "token": SECRET},
                                  {"kind": "multi", "label": "a", "base_url": URL, "token": ""},
                                  {"kind": "multi", "label": "a", "base_url": URL, "token": "has space"}])
def test_a_body_outside_the_schema_is_422_and_stores_nothing(client: TestClient, checks: Checks, db_url: str,
                                                              body: dict[str, str]) -> None:
    got = client.post("/api/connections", json=body, headers=ORIGIN)
    assert got.status_code == 422 and rows(db_url) == 0 and checks.given == []


# --- PUT ---------------------------------------------------------------------------------------------------------------


def test_put_replaces_address_and_secret_keeping_id_and_label_after_a_check(client: TestClient, checks: Checks,
                                                                           db_url: str) -> None:
    first = made(client, "multi", "work")
    aged = age(db_url, first["id"])
    checks.given.clear()
    got = client.put(f"/api/connections/{first['id']}", json={"base_url": "https://new.test", "token": "newer-0002"},
                     headers=ORIGIN)
    assert got.status_code == 200
    body = got.json()
    assert (body["id"], body["label"], body["base_url"]) == (first["id"], "work", "https://new.test")
    assert checks.given == [("https://new.test", "newer-0002")] and rows(db_url) == 1
    assert one(db_url, "SELECT checked_at FROM connections") > aged[1]
    assert listing(client)["connections"][0]["base_url"] == "https://new.test"


def test_put_that_the_service_refuses_is_400_and_changes_nothing(client: TestClient, checks: Checks,
                                                                  db_url: str) -> None:
    first = made(client)
    before = snapshot(db_url)
    checks.answer = "unreachable"
    got = client.put(f"/api/connections/{first['id']}", json={"base_url": "https://new.test", "token": "newer-0002"},
                     headers=ORIGIN)
    assert got.status_code == 400 and got.json()["reason"] == "unreachable" and snapshot(db_url) == before


def test_put_names_the_person_who_replaced_it(client: TestClient, people: People) -> None:
    first = made(client)
    as_(client, people, "sam")
    got = client.put(f"/api/connections/{first['id']}", json={"base_url": URL, "token": "newer-0002"}, headers=ORIGIN)
    assert got.status_code == 200 and got.json()["added_by"]["id"] == people.sam


def test_put_on_an_id_nothing_has_is_404(client: TestClient, db_url: str) -> None:
    got = client.put("/api/connections/9999999", json={"base_url": URL, "token": SECRET}, headers=ORIGIN)
    assert got.status_code == 404 and code(got) == "not_found" and rows(db_url) == 0


# --- PATCH -------------------------------------------------------------------------------------------------------------


def test_patch_relabels_and_does_not_move_checked_at_or_ask_the_service(client: TestClient, checks: Checks,
                                                                         db_url: str) -> None:
    first = made(client, "multi", "work")
    aged = age(db_url, first["id"])
    checks.given.clear()
    got = client.patch(f"/api/connections/{first['id']}", json={"label": "  laptop "}, headers=ORIGIN)
    assert got.status_code == 200 and got.json()["label"] == "laptop" and got.json()["id"] == first["id"]
    assert one(db_url, "SELECT checked_at FROM connections") == aged[1] and checks.given == []
    assert listing(client)["connections"][0]["label"] == "laptop"


def test_patch_to_a_taken_label_is_409_and_changes_nothing(client: TestClient, db_url: str) -> None:
    made(client, "multi", "taken")
    second = made(client, "multi", "mine")
    before = snapshot(db_url)
    got = client.patch(f"/api/connections/{second['id']}", json={"label": "taken"}, headers=ORIGIN)
    assert got.status_code == 409 and code(got) == "label_taken" and snapshot(db_url) == before


def test_patch_with_a_label_past_forty_characters_is_422(client: TestClient, db_url: str) -> None:
    first = made(client)
    before = snapshot(db_url)
    got = client.patch(f"/api/connections/{first['id']}", json={"label": "x" * 41}, headers=ORIGIN)
    assert got.status_code == 422 and snapshot(db_url) == before


def test_patch_on_an_id_nothing_has_is_404(client: TestClient) -> None:
    got = client.patch("/api/connections/9999999", json={"label": "a"}, headers=ORIGIN)
    assert got.status_code == 404 and code(got) == "not_found"


# --- DELETE ------------------------------------------------------------------------------------------------------------


def test_delete_removes_that_connection_alone_and_is_204_then_404(client: TestClient, db_url: str) -> None:
    a, b = made(client, "multi", "a"), made(client, "multi", "b")
    assert client.delete(f"/api/connections/{a['id']}", headers=ORIGIN).status_code == 204
    assert [c["id"] for c in listing(client)["connections"]] == [b["id"]] and rows(db_url) == 1
    got = client.delete(f"/api/connections/{a['id']}", headers=ORIGIN)
    assert got.status_code == 404 and code(got) == "not_found"


# --- the routes keyed by kind are gone -----------------------------------------------------------------------------------


def test_the_kind_keyed_routes_are_gone(client: TestClient, checks: Checks, db_url: str) -> None:
    first = made(client)
    before = snapshot(db_url)
    checks.given.clear()
    put = client.put("/api/connections/multi", json={"base_url": URL, "token": "x-0001"}, headers=ORIGIN)
    gone = client.delete("/api/connections/multi", headers=ORIGIN)
    assert put.status_code in (404, 405, 422) and gone.status_code in (404, 405, 422)
    assert snapshot(db_url) == before and checks.given == [] and first["id"]
    assert "/api/connections/{kind}" not in _paths(client)


def _paths(client: TestClient) -> dict[str, dict[str, object]]:
    app = client.app
    assert isinstance(app, FastAPI)
    return app.openapi()["paths"]


def test_the_id_routes_are_in_the_schema(client: TestClient) -> None:
    paths = _paths(client)
    assert {"post"} <= set(paths["/api/connections"]) and "get" in paths["/api/connections"]
    by_id = next(v for k, v in paths.items() if k.startswith("/api/connections/{") and k != "/api/connections/{kind}")
    assert {"put", "patch", "delete"} <= set(by_id)


# --- access ----------------------------------------------------------------------------------------------------------------


def test_signed_out_is_401_everywhere(client: TestClient) -> None:
    first = made(client)
    client.cookies.clear()
    i = first["id"]
    assert client.get("/api/connections").status_code == 401
    assert post(client).status_code == 401
    assert client.put(f"/api/connections/{i}", json={"base_url": URL, "token": SECRET}, headers=ORIGIN).status_code == 401
    assert client.patch(f"/api/connections/{i}", json={"label": "a"}, headers=ORIGIN).status_code == 401
    assert client.delete(f"/api/connections/{i}", headers=ORIGIN).status_code == 401


def test_without_the_key_every_write_is_503_unavailable_and_asks_nothing(keyless: TestClient, checks: Checks) -> None:
    got = post(keyless)
    assert got.status_code == 503 and code(got) == "unavailable" and SECRET not in got.text
    assert keyless.put("/api/connections/1", json={"base_url": URL, "token": SECRET}, headers=ORIGIN).status_code == 503
    assert keyless.patch("/api/connections/1", json={"label": "a"}, headers=ORIGIN).status_code == 503
    assert keyless.delete("/api/connections/1", headers=ORIGIN).status_code == 503
    assert checks.given == []
    listed = keyless.get("/api/connections")
    assert listed.status_code == 200 and listed.json()["can_connect"] is False


def test_a_write_from_another_site_is_403_and_changes_nothing(client: TestClient, db_url: str) -> None:
    first = made(client)
    before, other, i = snapshot(db_url), {"origin": "https://evil.test"}, first["id"]
    body = {"kind": "multi", "label": "z", "base_url": URL, "token": SECRET}
    assert client.post("/api/connections", json=body, headers=other).status_code == 403
    assert client.put(f"/api/connections/{i}", json={"base_url": URL, "token": SECRET}, headers=other).status_code == 403
    assert client.patch(f"/api/connections/{i}", json={"label": "z"}, headers=other).status_code == 403
    assert client.delete(f"/api/connections/{i}", headers=other).status_code == 403
    assert snapshot(db_url) == before
