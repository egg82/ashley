"""Sign-in end to end through the real app, a real database and the fake authentik: a browser signs in, is named by
`/api/me`, and signs out; a callback not from this browser's sign-in, an unmapped account or a forged write never signs
anyone in or out; unconfigured, starting a sign-in is 503 while the app runs; nothing secret or personal reaches the log."""

from collections.abc import Generator
from urllib.parse import urlsplit

import httpx2
import psycopg
import pytest
from ashley import services
from ashley.api.models import ErrorResponse, MeResponse, Person
from ashley.api.person import SESSION_COOKIE, SIGNIN_COOKIE, Person as PersonDep
from ashley.main import create_app
from ashley.people import admin
from ashley.settings import Settings
from ashley.signin.identity import sub_prefix
from ashley.signin.oidc import Oidc
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import scalar
from fastapi import FastAPI
from fastapi.testclient import TestClient
from signin_support import CLIENT, ISSUER, FakeAuthentik, oidc_for

PUBLIC = "https://ashley.test"
ORIGIN = {"origin": PUBLIC}


@pytest.fixture
def people(db_url: str) -> tuple[int, int]:
    with psycopg.connect(db_url) as conn:
        hid = admin.add_household(conn, "home", "America/Denver")
        pid = admin.add_person(conn, hid, "Alana")
        admin.add_account(conn, pid, "authentik", "sub-alana")
    return hid, pid


def no_client(app: FastAPI) -> bool:
    """The built web client's catch-all would shadow the route a test adds after `create_app`."""
    return False


@pytest.fixture
def fake() -> FakeAuthentik:
    return FakeAuthentik(sub="sub-alana", username="zqUSERNAME")


@pytest.fixture
def client(db_url: str, people: tuple[int, int], fake: FakeAuthentik,
           monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient]:
    monkeypatch.setattr("ashley.main.mount_client", no_client)
    app = create_app(Settings(database_url=db_url, build_version="t", oidc_issuer=ISSUER,
                              oidc_client_id=CLIENT.client_id, oidc_client_secret=CLIENT.client_secret,
                              public_url=PUBLIC))
    services.register(Oidc, oidc_for(fake))

    @app.post("/api/test-write", status_code=204)
    async def write(_: PersonDep) -> None:
        """A write made with the cookie, as a person's routes will make them."""
    with TestClient(app, base_url=PUBLIC, follow_redirects=False) as c:
        yield c


def sign_in(client: TestClient, fake: FakeAuthentik, next_: str = "/memory") -> httpx2.Response:
    started = client.get("/api/auth/signin", params={"next": next_})
    assert started.status_code == 302
    code, state = fake.authorize(started.headers["location"])
    return client.get("/api/auth/callback", params={"code": code, "state": state})


def test_a_browser_signs_in_is_named_and_signs_out(client: TestClient, fake: FakeAuthentik,
                                                   people: tuple[int, int]) -> None:
    done = sign_in(client, fake)
    assert (done.status_code, done.headers["location"]) == (302, "/memory")
    me = client.get("/api/me")
    assert me.status_code == 200
    assert MeResponse.model_validate(me.json()) == MeResponse(person=Person(id=people[1], household_id=people[0],
                                                                            name="Alana"))
    out = client.post("/api/auth/signout", headers=ORIGIN)
    assert out.status_code == 204
    cleared = next(v for v in out.headers.get_list("set-cookie") if v.startswith(SESSION_COOKIE + "="))
    assert "max-age=0" in cleared.lower()
    assert client.get("/api/me").status_code == 401


def test_the_cookies_are_host_only_secure_httponly_lax(client: TestClient, fake: FakeAuthentik) -> None:
    started = client.get("/api/auth/signin")
    code, state = fake.authorize(started.headers["location"])
    done = client.get("/api/auth/callback", params={"code": code, "state": state})
    for response, name in ((started, SIGNIN_COOKIE), (done, SESSION_COOKIE)):
        cookie = next(v for v in response.headers.get_list("set-cookie") if v.startswith(name + "="))
        flags = {part.strip().split("=")[0].lower() for part in cookie.split(";")}
        assert {"secure", "httponly", "path", "max-age"} <= flags and "domain" not in flags
        assert "samesite=lax" in cookie.lower() and "path=/" in cookie.lower()


def test_a_callback_from_another_browser_signs_no_one_in(client: TestClient, fake: FakeAuthentik) -> None:
    started = client.get("/api/auth/signin")
    code, state = fake.authorize(started.headers["location"])
    client.cookies.clear()
    done = client.get("/api/auth/callback", params={"code": code, "state": state})
    assert done.headers["location"] == "/?signin=failed"
    assert client.get("/api/me").status_code == 401


def test_a_state_is_taken_once(client: TestClient, fake: FakeAuthentik) -> None:
    started = client.get("/api/auth/signin")
    code, state = fake.authorize(started.headers["location"])
    cookie = started.cookies[SIGNIN_COOKIE]
    assert client.get("/api/auth/callback", params={"code": code, "state": state}).headers["location"] == "/"
    client.cookies.clear()
    client.cookies.set(SIGNIN_COOKIE, cookie, domain="ashley.test")
    again = client.get("/api/auth/callback", params={"code": code, "state": state})
    assert again.headers["location"] == "/?signin=failed"


def test_an_unmapped_account_is_refused_and_listed_by_its_hash(client: TestClient, fake: FakeAuthentik, db_url: str,
                                                               capsys: pytest.CaptureFixture[str]) -> None:
    fake.sub = "sub-zqSTRANGER"
    capsys.readouterr()
    done = sign_in(client, fake)
    assert done.headers["location"] == "/?signin=unmapped"
    out = capsys.readouterr().out
    assert f"reason=unmapped sub={sub_prefix(fake.sub)}" in out and "zqSTRANGER" not in out
    assert scalar(db_url, "SELECT username FROM signin_unmapped WHERE external_id = %s", (fake.sub,)) == "zqUSERNAME"
    assert client.get("/api/me").status_code == 401


def test_an_error_from_authentik_is_a_refusal(client: TestClient, fake: FakeAuthentik) -> None:
    started = client.get("/api/auth/signin")
    code, state = fake.authorize(started.headers["location"])
    done = client.get("/api/auth/callback", params={"error": "access_denied", "code": code, "state": state})
    assert done.headers["location"] == "/?signin=failed"
    assert client.get("/api/me").status_code == 401


@pytest.mark.parametrize(("sent", "logged"), [("invalid_request", "invalid_request"),
                                              ("x reason=forged\nevent=signin.ok", "other")])
def test_a_refusal_by_authentik_logs_its_error_code_and_nothing_else(
        client: TestClient, fake: FakeAuthentik, capsys: pytest.CaptureFixture[str], sent: str, logged: str) -> None:
    started = client.get("/api/auth/signin")
    _, state = fake.authorize(started.headers["location"])
    capsys.readouterr()
    client.get("/api/auth/callback", params={"error": sent, "state": state})
    out = capsys.readouterr().out
    assert f"reason=provider_error error={logged}" in out
    assert "forged" not in out and "event=signin.ok" not in out


@pytest.mark.parametrize("next_",["//evil.test/x", "https://evil.test/", "/\\evil.test", "memory"])
def test_next_returns_only_to_a_path_on_this_site(client: TestClient, fake: FakeAuthentik, next_: str) -> None:
    assert sign_in(client, fake, next_).headers["location"] == "/"


@pytest.mark.parametrize("headers", [
    {"origin": "https://evil.test"},
    {"origin": "http://ashley.test"},
    {"origin": "null"},
    {"sec-fetch-site": "cross-site"},
    {"origin": PUBLIC, "content-type": "text/plain"},
])
def test_a_forged_sign_out_is_403_and_signs_no_one_out(client: TestClient, fake: FakeAuthentik,
                                                       headers: dict[str, str]) -> None:
    sign_in(client, fake)
    body = "x" if "content-type" in headers else None
    refused = client.post("/api/auth/signout", headers=headers, content=body)
    assert refused.status_code == 403
    assert ErrorResponse.model_validate(refused.json()).code == "forbidden"
    assert client.get("/api/me").status_code == 200


def test_signing_in_again_ends_the_session_before(client: TestClient, fake: FakeAuthentik) -> None:
    sign_in(client, fake)
    first = client.cookies[SESSION_COOKIE]
    sign_in(client, fake)
    assert client.cookies[SESSION_COOKIE] != first
    client.cookies.set(SESSION_COOKIE, first, domain="ashley.test")
    assert client.get("/api/me").status_code == 401


def test_nothing_secret_or_personal_is_logged(client: TestClient, fake: FakeAuthentik,
                                              capsys: pytest.CaptureFixture[str]) -> None:
    capsys.readouterr()
    started = client.get("/api/auth/signin")
    code, state = fake.authorize(started.headers["location"])
    client.get("/api/auth/callback", params={"code": code, "state": state})
    token = client.cookies[SESSION_COOKIE]
    client.get("/api/me")
    client.post("/api/auth/signout", headers=ORIGIN)
    out = capsys.readouterr().out
    assert "event=signin.ok" in out and "event=signout" in out
    assert not [m for m in (code, state, token, "zqUSERNAME", "sub-alana", "Alana", "example.test") if m in out]


def test_unconfigured_sign_in_is_503_and_the_app_runs(db_url: str) -> None:
    app = create_app(Settings(database_url=db_url, build_version="t"))
    with TestClient(app, base_url=PUBLIC, follow_redirects=False) as c:
        response = c.get("/api/auth/signin")
        assert response.status_code == 503
        assert ErrorResponse.model_validate(response.json()).code == "unavailable"
        assert scalar(db_url, "SELECT count(*) FROM signin_pending") == 0, "nothing is stored for a sign-in never sent"
        assert c.get("/api/me").status_code == 401
        assert c.get("/api/health").status_code == 200


def test_the_authorization_url_is_authentiks(client: TestClient) -> None:
    location = client.get("/api/auth/signin").headers["location"]
    assert urlsplit(location).netloc == "auth.test"


@pytest.mark.parametrize(("headers", "status"), [
    ({"origin": "https://evil.test"}, 403), ({"sec-fetch-site": "cross-site"}, 403), (ORIGIN, 204), ({}, 204)])
def test_a_write_with_the_cookie_must_come_from_this_site(client: TestClient, fake: FakeAuthentik,
                                                          headers: dict[str, str], status: int) -> None:
    sign_in(client, fake)
    assert client.post("/api/test-write", headers=headers).status_code == status


def test_a_write_without_a_session_is_401(client: TestClient) -> None:
    assert client.post("/api/test-write", headers=ORIGIN).status_code == 401
