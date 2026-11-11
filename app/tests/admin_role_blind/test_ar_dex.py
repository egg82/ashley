"""Provider mode against a real Dex: the app asks for the `groups` scope, and the static user's `groups` claim decides
admin. Needs `ASHLEY_TEST_DEX_URL` (skips unset locally, fails under CI). `tests/dex/config.yaml` puts the static user in
`DEX_GROUP`."""

from collections.abc import Generator
from urllib.parse import parse_qs, urlsplit

import psycopg
import pytest
from admin_role_blind_support import PUBLIC, me, no_client
from ashley.api.person import SESSION_COOKIE
from ashley.main import create_app
from ashley.people import admin
from ashley.settings import Settings
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template, scalar
from fastapi.testclient import TestClient
from signin_dex_support import PASSWORD, dex_issuer, log_in

DEX_GROUP = "ashley-test-admins"
NOT_DEX_GROUP = "a-group-dex-does-not-name"


def app_for(url: str, group: str, monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient]:
    monkeypatch.setattr("ashley.main.mount_client", no_client)
    app = create_app(Settings(database_url=url, build_version="t", oidc_issuer=dex_issuer(), oidc_client_id="ashley-test",
                              oidc_client_secret="ashley-test-secret", public_url=PUBLIC, admin_group=group))
    with TestClient(app, base_url=PUBLIC, follow_redirects=False) as client:
        yield client


def browse(client: TestClient) -> str:
    started = client.get("/api/auth/signin", params={"next": "/"})
    assert started.status_code == 302, started.text
    code, state = log_in(started.headers["location"], PASSWORD)
    return client.get("/api/auth/callback", params={"code": code, "state": state}).headers["location"]


def map_the_dex_user(url: str, client: TestClient) -> int:
    """The static user's first sign-in is refused as unmapped; map the sub it carried to a person, as an operator does."""
    assert browse(client) == "/?signin=unmapped"
    sub = str(scalar(url, "SELECT external_id FROM signin_unmapped LIMIT 1"))
    with psycopg.connect(url) as conn:
        home = admin.add_household(conn, "home", "UTC")
        person = admin.add_person(conn, home, "Alana")
        admin.add_account(conn, person, "oidc", sub)
    return person


@pytest.fixture
def dex_member(db_url: str, monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient]:
    yield from app_for(db_url, DEX_GROUP, monkeypatch)


@pytest.fixture
def dex_outsider(db_url: str, monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient]:
    yield from app_for(db_url, NOT_DEX_GROUP, monkeypatch)


def test_dex_the_groups_scope_is_requested(dex_member: TestClient) -> None:
    started = dex_member.get("/api/auth/signin")
    scope = parse_qs(urlsplit(started.headers["location"]).query)["scope"][0].split()
    assert "groups" in scope and "openid" in scope


def test_dex_a_member_of_the_group_is_admin_after_sign_in(db_url: str, dex_member: TestClient) -> None:
    person = map_the_dex_user(db_url, dex_member)
    assert browse(dex_member) == "/"
    assert me(dex_member) == {"id": person, "household_id": 1, "name": "Alana", "admin": True}


def test_dex_a_former_admin_outside_the_group_loses_it_at_sign_in(db_url: str, dex_outsider: TestClient) -> None:
    person = map_the_dex_user(db_url, dex_outsider)
    with psycopg.connect(db_url) as conn:
        conn.execute("UPDATE people SET admin = true WHERE id = %s", (person,))
    assert browse(dex_outsider) == "/"
    assert me(dex_outsider)["admin"] is False
    assert dex_outsider.cookies.get(SESSION_COOKIE) is not None
