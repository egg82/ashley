"""The people routes over a real database (`ashley.api.people`): any person lists their own household's people with who
is an admin; only an admin grants or revokes, never the last admin away, never for another household's person, and never
while the provider's group decides."""

import pytest
from admin_role_support import (GROUP, ORIGIN, Deployment, admins, app_client, as_browser, deployment, session_for,
                                set_admin)
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from fastapi.testclient import TestClient
from signin_support import FakeIdp



@pytest.fixture
def home(db_url: str) -> Deployment:
    found = deployment(db_url)
    set_admin(db_url, found.ana)
    return found


def put(client: TestClient, person: int, admin: bool) -> tuple[int, dict[str, object]]:
    got = client.put(f"/api/people/{person}/admin", json={"admin": admin}, headers=ORIGIN)
    body: dict[str, object] = got.json()
    return got.status_code, body


def test_any_person_lists_their_households_people_with_who_is_admin(home: Deployment) -> None:
    for client in app_client(home.url, FakeIdp()):
        as_browser(client, session_for(home.url, home.ben))
        listed = client.get("/api/people").json()
        assert listed["admins_from"] == "app"
        assert [(p["id"], p["admin"]) for p in listed["people"]] == [(home.ana, True), (home.ben, False),
                                                                    (home.cy, False)]


def test_an_admin_grants_and_revokes(home: Deployment) -> None:
    for client in app_client(home.url, FakeIdp()):
        as_browser(client, session_for(home.url, home.ana))
        status, body = put(client, home.ben, True)
        assert (status, body["id"], body["admin"]) == (200, home.ben, True)
        assert admins(home.url) == [home.ana, home.ben]
        status, body = put(client, home.ben, False)
        assert (status, body["admin"]) == (200, False)
        assert admins(home.url) == [home.ana]


def test_the_last_admin_cannot_be_revoked(home: Deployment) -> None:
    for client in app_client(home.url, FakeIdp()):
        as_browser(client, session_for(home.url, home.ana))
        status, body = put(client, home.ana, False)
        assert (status, body["code"]) == (409, "last_admin")
    assert admins(home.url) == [home.ana]


def test_a_non_admin_cannot_grant(home: Deployment) -> None:
    for client in app_client(home.url, FakeIdp()):
        as_browser(client, session_for(home.url, home.ben))
        status, body = put(client, home.ben, True)
        assert (status, body["code"]) == (403, "admin_only")
    assert admins(home.url) == [home.ana]


def test_another_households_person_is_not_found(home: Deployment) -> None:
    for client in app_client(home.url, FakeIdp()):
        as_browser(client, session_for(home.url, home.ana))
        status, body = put(client, home.kim, True)
        assert (status, body["code"]) == (404, "not_found")
    assert admins(home.url) == [home.ana]


def test_under_the_group_grant_and_revoke_are_refused(home: Deployment) -> None:
    for client in app_client(home.url, FakeIdp(), GROUP):
        as_browser(client, session_for(home.url, home.ana, admin_now=True))
        for person, value in ((home.ben, True), (home.ana, False)):
            status, body = put(client, person, value)
            assert (status, body["code"]) == (409, "admins_from_provider")
    assert admins(home.url) == [home.ana]
