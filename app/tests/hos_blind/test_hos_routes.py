"""`PUT/DELETE /api/connections/gitlab|github` and `GET /api/connections` through the real app on a real database and the
fake forges: checked with one authenticated read before anything is stored, nothing stored on a refusal, a person's code
host listed, replaced and removed only by them, and the token never in a response, an error or a log."""

import asyncio
import base64
import hashlib
import os
import secrets
from collections.abc import Generator
from dataclasses import dataclass

import httpx2
import psycopg
import pytest
from ashley import services
from ashley.api.connection_models import ConnectionRefused, ConnectionsResponse, HouseholdConnection
from ashley.api.person import SESSION_COOKIE
from ashley.codehost.host import CodeHost
from ashley.connections.connections import Connections, ConnectionsUnavailable
from ashley.connections.model import Kind
from ashley.main import create_app
from ashley.people import admin
from ashley.settings import Settings
from contract.conversations_support import scalar
from fastapi.testclient import TestClient
from hos_support import GH_ALANA, GH_SAM, GL_ALANA, GL_KIM, GL_SAM, all_logs, connections, log_text, world
from hos_forges_support import Forges, standard
from connection_legacy_support import opened_of, put_of
from connection_routes_support import delete_kind, put_kind

PUBLIC = "https://ashley.test"
ORIGIN = {"origin": PUBLIC}
APP_KEY = base64.b64encode(os.urandom(32)).decode()
BASE = "https://gitlab.test"


def session(conn: psycopg.Connection, person: int, household: int, sub: str) -> str:
    account = admin.add_account(conn, person, "authentik", sub)
    token = secrets.token_urlsafe(16)
    conn.execute("INSERT INTO sessions (token_sha256, account_id, household_id, expires_at) "
                 "VALUES (%s, %s, %s, now() + interval '1 day')",
                 (hashlib.sha256(token.encode()).digest(), account, household))
    return token


@dataclass
class Rig:
    client: TestClient
    forges: Forges
    cookies: dict[str, str]
    ids: dict[str, int]
    household: dict[str, int]
    url: str

    def as_(self, who: str) -> None:
        self.client.cookies.clear()
        if who:
            self.client.cookies.set(SESSION_COOKIE, self.cookies[who], domain="ashley.test")

    def put(self, kind: str, who: str, body: dict[str, str], headers: dict[str, str] | None = None) -> httpx2.Response:
        self.as_(who)
        return put_kind(self.client, kind, json=body, headers=ORIGIN if headers is None else headers)

    def listed(self, who: str) -> ConnectionsResponse:
        self.as_(who)
        got = self.client.get("/api/connections")
        assert got.status_code == 200, got.text
        return ConnectionsResponse.model_validate(got.json())

    def delete(self, kind: str, who: str, headers: dict[str, str] | None = None) -> httpx2.Response:
        self.as_(who)
        return delete_kind(self.client, kind, headers=ORIGIN if headers is None else headers)

    def kinds(self, who: str) -> list[str]:
        return sorted(c.kind for c in self.listed(who).connections)

    def rows(self) -> int:
        return int(scalar(self.url, "SELECT count(*) FROM connections"))

    def opened(self, who: str, kind: Kind) -> str | None:
        async def read() -> str | None:
            got = await opened_of(services.get(Connections), self.household[who], kind, self.ids[who])
            return None if got is None else got.secret

        return asyncio.run(read())


def make(url: str, forges: Forges, key: str = APP_KEY) -> Generator[Rig]:
    w = world(url)
    with psycopg.connect(url) as conn:
        cookies = {"alana": session(conn, w.alana, w.home, "a"), "sam": session(conn, w.sam, w.home, "s"),
                   "lee": session(conn, w.lee, w.home, "l"), "kim": session(conn, w.kim, w.other, "k")}
    ids = {"alana": w.alana, "sam": w.sam, "lee": w.lee, "kim": w.kim}
    households = {"alana": w.home, "sam": w.home, "lee": w.home, "kim": w.other}
    app = create_app(Settings(database_url=url, build_version="t", public_url=PUBLIC, connections_key=key))
    with TestClient(app, base_url=PUBLIC, follow_redirects=False) as c:
        services.register(CodeHost, forges.routed())
        yield Rig(c, forges, cookies, ids, households, url)


@pytest.fixture
def forges() -> Forges:
    return standard()


@pytest.fixture
def rig(db_url: str, forges: Forges) -> Generator[Rig]:
    yield from make(db_url, forges)


def test_a_person_connects_their_gitlab_and_it_is_checked_with_their_token_first(rig: Rig) -> None:
    got = rig.put("gitlab", "alana", {"base_url": BASE, "token": GL_ALANA})
    assert got.status_code == 200, got.text
    shown = HouseholdConnection.model_validate(got.json())
    assert (shown.kind, shown.personal, shown.base_url) == ("gitlab", True, BASE)
    assert shown.added_by is not None and shown.added_by.id == rig.ids["alana"]
    assert GL_ALANA not in got.text
    assert rig.forges.seen and {s.headers.get("private-token") for s in rig.forges.seen} == {GL_ALANA}
    assert {s.host for s in rig.forges.seen} == {"gitlab.test"} and all(s.method == "GET" for s in rig.forges.seen)
    assert rig.opened("alana", "gitlab") == GL_ALANA


def test_a_person_connects_their_github_by_token_alone(rig: Rig) -> None:
    got = rig.put("github", "alana", {"token": GH_ALANA})
    assert got.status_code == 200, got.text
    shown = HouseholdConnection.model_validate(got.json())
    assert (shown.kind, shown.personal) == ("github", True) and GH_ALANA not in got.text
    assert {s.host for s in rig.forges.seen} == {"api.github.com"}
    assert {s.headers.get("authorization") for s in rig.forges.seen} == {f"Bearer {GH_ALANA}"}
    assert rig.opened("alana", "github") == GH_ALANA


def test_a_code_host_is_listed_to_its_person_and_to_no_one_else(rig: Rig) -> None:
    assert rig.put("gitlab", "alana", {"base_url": BASE, "token": GL_ALANA}).status_code == 200
    assert rig.put("github", "sam", {"token": GH_SAM}).status_code == 200
    assert rig.kinds("alana") == ["gitlab"] and rig.kinds("sam") == ["github"]
    assert rig.kinds("lee") == [] and rig.kinds("kim") == []
    for who in ("lee", "kim", "sam"):
        assert GL_ALANA not in rig.client.get("/api/connections").text
        assert "gitlab" not in rig.kinds(who)


def test_the_households_own_connections_are_listed_to_all_of_it_beside_a_persons_own(rig: Rig, db_url: str) -> None:
    async def seed() -> None:
        async with connections(db_url) as c:
            await put_of(c, rig.household["alana"], "sure", "https://money.test", "sure-key", rig.ids["alana"])

    asyncio.run(seed())
    rig.put("gitlab", "alana", {"base_url": BASE, "token": GL_ALANA})
    assert rig.kinds("alana") == ["gitlab", "sure"] and rig.kinds("lee") == ["sure"] and rig.kinds("kim") == []


def test_a_second_put_replaces_the_persons_own_and_no_one_elses(rig: Rig) -> None:
    rig.put("gitlab", "alana", {"base_url": BASE, "token": GL_ALANA})
    rig.put("gitlab", "sam", {"base_url": BASE, "token": GL_SAM})
    assert rig.rows() == 2
    again = rig.put("gitlab", "alana", {"base_url": "https://gitlab.test/git", "token": GL_ALANA})
    assert again.status_code == 200 and rig.rows() == 2
    assert [c.base_url for c in rig.listed("alana").connections] == ["https://gitlab.test/git"]
    assert [c.base_url for c in rig.listed("sam").connections] == [BASE]
    assert rig.opened("sam", "gitlab") == GL_SAM and rig.opened("alana", "gitlab") == GL_ALANA


def test_a_person_removes_only_their_own_and_another_gets_not_found(rig: Rig) -> None:
    rig.put("gitlab", "alana", {"base_url": BASE, "token": GL_ALANA})
    rig.put("gitlab", "sam", {"base_url": BASE, "token": GL_SAM})
    for who in ("lee", "kim"):
        got = rig.delete("gitlab", who)
        assert got.status_code == 404 and got.json()["code"] == "not_found"
    assert rig.rows() == 2
    assert rig.delete("gitlab", "alana").status_code == 204
    assert rig.kinds("alana") == [] and rig.kinds("sam") == ["gitlab"] and rig.opened("sam", "gitlab") == GL_SAM
    assert rig.delete("gitlab", "alana").status_code == 404 and rig.delete("github", "sam").status_code == 404
    assert rig.rows() == 1


def test_a_token_the_host_turns_away_is_refused_and_nothing_is_stored(rig: Rig) -> None:
    got = rig.put("gitlab", "alana", {"base_url": BASE, "token": "not-a-token-at-all"})
    assert got.status_code == 400 and ConnectionRefused.model_validate(got.json()).reason == "key_refused"
    assert rig.rows() == 0 and rig.kinds("alana") == [] and "not-a-token-at-all" not in got.text
    got = rig.put("github", "alana", {"token": "not-a-token-at-all"})
    assert got.status_code == 400 and ConnectionRefused.model_validate(got.json()).reason == "key_refused"
    assert rig.rows() == 0


def test_a_host_that_does_not_answer_is_unreachable_and_nothing_is_stored(rig: Rig) -> None:
    rig.forges.down.add("gitlab.test")
    got = rig.put("gitlab", "alana", {"base_url": BASE, "token": GL_ALANA})
    assert got.status_code == 400 and ConnectionRefused.model_validate(got.json()).reason == "unreachable"
    rig.forges.down.add("api.github.com")
    got = rig.put("github", "alana", {"token": GH_ALANA})
    assert got.status_code == 400 and ConnectionRefused.model_validate(got.json()).reason == "unreachable"
    assert rig.rows() == 0


def test_something_that_is_not_a_code_host_is_refused_and_nothing_is_stored(rig: Rig) -> None:
    rig.forges.script.append(("gitlab.test", "/", lambda r: httpx2.Response(
        200, content=b"<html>login</html>", headers={"content-type": "text/html"})))
    got = rig.put("gitlab", "alana", {"base_url": BASE, "token": GL_ALANA})
    assert got.status_code == 400 and ConnectionRefused.model_validate(got.json()).reason == "wrong_service"
    assert rig.rows() == 0


def test_a_redirect_is_not_followed_and_is_refused(rig: Rig) -> None:
    rig.forges.script.append(("gitlab.test", "/", lambda r: httpx2.Response(
        302, headers={"location": "https://evil.test/collect"})))
    got = rig.put("gitlab", "alana", {"base_url": BASE, "token": GL_ALANA})
    assert got.status_code == 400 and rig.rows() == 0
    assert rig.forges.to("evil.test") == [] and GL_ALANA not in got.text


@pytest.mark.parametrize("base", ["http://gitlab.test", "ftp://gitlab.test", "gitlab.test", "https://u:p@gitlab.test",
                                  "https://gitlab.test?x=1", "https://gitlab.test#f", "https://gitlab.test:99999",
                                  "https://", "javascript:alert(1)"])
def test_an_address_that_is_not_an_https_address_is_refused_before_any_request(rig: Rig, base: str) -> None:
    got = rig.put("gitlab", "alana", {"base_url": base, "token": GL_ALANA})
    assert got.status_code == 400 and ConnectionRefused.model_validate(got.json()).reason == "bad_url"
    assert rig.forges.seen == [] and rig.rows() == 0 and GL_ALANA not in got.text


@pytest.mark.parametrize("token", ["has a space", "tab\there", " leading", "x" * 501, "", "new\nline"])
def test_a_token_outside_the_schema_is_a_422_that_does_not_echo_it_and_stores_nothing(
        rig: Rig, caplog: pytest.LogCaptureFixture, token: str) -> None:
    all_logs(caplog)
    for kind, body in (("gitlab", {"base_url": BASE, "token": token}), ("github", {"token": token})):
        got = rig.put(kind, "alana", body)
        assert got.status_code == 422
        if len(token) > 5:
            assert token not in got.text and token.strip() not in got.text
    assert rig.forges.seen == [] and rig.rows() == 0
    if len(token) > 5:
        assert token.strip() not in log_text(caplog)


def test_who_may_ask(rig: Rig) -> None:
    for call in (lambda: rig.put("gitlab", "", {"base_url": BASE, "token": GL_ALANA}), lambda: rig.delete("gitlab", "")):
        got = call()
        assert got.status_code == 401 and got.json()["code"] == "unauthorized"
    rig.as_("")
    assert rig.client.get("/api/connections").status_code == 401
    assert rig.forges.seen == [] and rig.rows() == 0


def test_a_request_from_another_site_is_forbidden_and_changes_nothing(rig: Rig) -> None:
    got = rig.put("gitlab", "alana", {"base_url": BASE, "token": GL_ALANA}, {"origin": "https://evil.test"})
    assert got.status_code == 403 and got.json()["code"] == "forbidden" and rig.rows() == 0
    rig.put("gitlab", "alana", {"base_url": BASE, "token": GL_ALANA})
    assert rig.delete("gitlab", "alana", {"origin": "https://evil.test"}).status_code == 403
    assert rig.rows() == 1 and rig.opened("alana", "gitlab") == GL_ALANA


def test_an_unknown_kind_is_not_a_connection_route(rig: Rig) -> None:
    rig.put("gitlab", "alana", {"base_url": BASE, "token": GL_ALANA})
    assert rig.put("bitbucket", "alana", {"base_url": BASE, "token": GL_ALANA}).status_code in (404, 405, 422)
    assert rig.delete("bitbucket", "alana").status_code in (404, 405, 422)
    assert rig.rows() == 1


def test_without_the_key_nothing_is_connected_and_the_list_says_so(db_url: str, forges: Forges) -> None:
    for r in make(db_url, forges, key=""):
        listed = r.listed("alana")
        assert listed.can_connect is False and listed.connections == []
        got = r.put("gitlab", "alana", {"base_url": BASE, "token": GL_ALANA})
        assert got.status_code == 503 and got.json()["code"] == "unavailable"
        refused = r.put("gitlab", "alana", {"base_url": "http://not-https.test", "token": GL_ALANA})
        assert refused.status_code == 503 and refused.json()["code"] == "unavailable"
        assert r.delete("gitlab", "alana").status_code in (503, 404)
        assert r.rows() == 0 and GL_ALANA not in got.text


def test_the_token_the_address_and_the_secret_are_in_no_log_and_not_the_table(
        rig: Rig, caplog: pytest.LogCaptureFixture) -> None:
    all_logs(caplog)
    address = "https://gitlab.test/secret-prefix-xyz"
    rig.forges.script.append(("gitlab.test", "/secret-prefix-xyz/api/v4/user", lambda r: httpx2.Response(
        200, content=b'{"id": 1}', headers={"content-type": "application/json"})))
    assert rig.put("gitlab", "alana", {"base_url": address, "token": GL_ALANA}).status_code == 200
    rig.put("gitlab", "sam", {"base_url": address, "token": "not-a-valid-token-xyz"})
    rig.put("github", "alana", {"token": GH_ALANA})
    rig.listed("alana")
    rig.delete("gitlab", "alana")
    everywhere, hers = log_text(caplog), log_text(caplog, "ashley")
    for secret in (GL_ALANA, GH_ALANA, "not-a-valid-token-xyz"):
        assert secret not in everywhere, secret
    assert "secret-prefix-xyz" not in hers
    assert GH_ALANA.encode() not in bytes(scalar(rig.url, "SELECT secret FROM connections WHERE kind = 'github'"))
    assert "ashley.api" in hers


def test_a_secret_cannot_be_read_back_through_any_route(rig: Rig) -> None:
    rig.put("gitlab", "alana", {"base_url": BASE, "token": GL_ALANA})
    rig.put("github", "alana", {"token": GH_ALANA})
    got = rig.client.get("/api/connections")
    shown = str(got.json()["connections"])
    assert GL_ALANA not in got.text and GH_ALANA not in got.text and "token" not in shown.lower().replace("personal", "")


def test_the_sealed_secret_is_not_the_token_and_is_bound_to_its_person(rig: Rig) -> None:
    rig.put("gitlab", "alana", {"base_url": BASE, "token": GL_ALANA})
    rig.put("gitlab", "sam", {"base_url": BASE, "token": GL_SAM})
    assert rig.rows() == 2
    with psycopg.connect(rig.url, autocommit=True) as conn:
        conn.execute("UPDATE connections SET secret = (SELECT secret FROM connections WHERE person_id = %s) "
                     "WHERE person_id = %s", (rig.ids["alana"], rig.ids["sam"]))
    assert rig.opened("alana", "gitlab") == GL_ALANA
    with pytest.raises(ConnectionsUnavailable):
        rig.opened("sam", "gitlab")


def test_another_households_person_can_hold_the_same_kind_and_neither_sees_the_other(rig: Rig) -> None:
    assert rig.put("gitlab", "alana", {"base_url": BASE, "token": GL_ALANA}).status_code == 200
    assert rig.put("gitlab", "kim", {"base_url": BASE, "token": GL_KIM}).status_code == 200
    assert rig.kinds("alana") == ["gitlab"] and rig.kinds("kim") == ["gitlab"]
    assert rig.delete("gitlab", "kim").status_code == 204
    assert rig.kinds("alana") == ["gitlab"] and rig.opened("alana", "gitlab") == GL_ALANA
