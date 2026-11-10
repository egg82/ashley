"""Connecting a Google account end to end through the real app, a real database and Google's endpoints faked at their
HTTP boundary: the connect is bound to the person who started it, taken once and stored only after userinfo answers; the
refresh token and access token are sealed, the granted scopes kept; a reconnect replaces the tokens and clears `needs`;
unset, starting is 503; nothing secret is logged."""

import psycopg
import pytest
from ashley import services
from ashley.api.connection_models import ConnectionsResponse
from ashley.connections.oauth import OAuthProviders
from ashley.connections.sealing import Sealer, key_from
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import scalar
from fastapi.testclient import TestClient
from oauth_google_support import SCOPES, FakeGoogle
from oauth_home_support import (KEY, ORIGIN, Home, as_, back, client as client, connect, google as google,
                                home as home, start)

DONE = "/connections?connect="


def listed(client: TestClient) -> ConnectionsResponse:
    got = client.get("/api/connections")
    assert got.status_code == 200
    return ConnectionsResponse.model_validate(got.json())


def rows(db_url: str) -> int:
    return int(scalar(db_url, "SELECT count(*) FROM connections"))


def test_a_person_connects_google_and_the_row_holds_sealed_tokens(client: TestClient, google: FakeGoogle, home: Home,
                                                                  db_url: str) -> None:
    assert connect(client, google, "main") == f"{DONE}connected"
    mine = listed(client).connections
    assert [(c.kind, c.label, c.personal, c.needs, c.scopes) for c in mine] == [
        ("google", "main", True, None, SCOPES.split())]
    with psycopg.connect(db_url) as conn:
        row = conn.execute("SELECT person_id, secret, access_token, secret_version, "
                           "extract(epoch FROM access_expires_at - now()) FROM connections").fetchone()
    assert row is not None and row[0] == home.alana and row[3] == 1 and 3500 < row[4] <= 3600
    sealer = Sealer({1: key_from(KEY)})
    bound = f"connection:{home.household}:google:{home.alana}".encode()
    assert sealer.open(bytes(row[1]), bound) in google.refresh_tokens
    assert sealer.open(bytes(row[2]), bound) in google.access_tokens
    assert ("userinfo", sealer.open(bytes(row[2]), bound)) in google.seen


def test_a_connection_is_stored_only_after_userinfo_answers(client: TestClient, google: FakeGoogle,
                                                            db_url: str) -> None:
    google.refuse_userinfo = True
    assert connect(client, google) == f"{DONE}refused"
    assert rows(db_url) == 0


def test_the_pending_row_holds_only_hashes_and_a_sealed_verifier(client: TestClient, google: FakeGoogle, home: Home,
                                                                 db_url: str) -> None:
    code, state = start(client, google, "main")
    with psycopg.connect(db_url) as conn:
        row = conn.execute("SELECT state_sha256, person_id, kind, label, holder, verifier FROM connect_pending"
                           ).fetchone()
    assert row is not None and len(bytes(row[0])) == 32 and state.encode() not in bytes(row[0])
    assert (row[1], row[2], row[3], row[4]) == (home.alana, "google", "main", "person")
    assert Sealer({1: key_from(KEY)}).open(bytes(row[5]), f"connect:{home.household}:{home.alana}".encode())
    assert back(client, code=code, state=state) == f"{DONE}connected"
    assert scalar(db_url, "SELECT count(*) FROM connect_pending") == 0


def test_a_connect_finishes_only_for_the_person_who_started_it_and_only_once(client: TestClient, google: FakeGoogle,
                                                                           home: Home, db_url: str) -> None:
    code, state = start(client, google)
    as_(client, home.sam_token)
    assert back(client, code=code, state=state) == f"{DONE}wrong_person"
    as_(client, home.alana_token)
    assert back(client, code=code, state=state) == f"{DONE}failed", "the refusal took the state"
    assert rows(db_url) == 0
    code, state = start(client, google)
    assert back(client, code=code, state=state) == f"{DONE}connected"
    assert back(client, code=code, state=state) == f"{DONE}failed"


def test_an_unknown_expired_or_missing_state_and_a_missing_session_fail(client: TestClient, google: FakeGoogle,
                                                                       db_url: str) -> None:
    code, state = start(client, google)
    assert back(client, code=code, state="nope") == f"{DONE}failed"
    assert back(client, code=code) == f"{DONE}failed"
    with psycopg.connect(db_url) as conn:
        conn.execute("UPDATE connect_pending SET created_at = now() - interval '1 day'")
    assert back(client, code=code, state=state) == f"{DONE}failed"
    client.cookies.clear()
    assert back(client, code=code, state=state) == f"{DONE}failed"
    assert rows(db_url) == 0


def test_declining_at_google_stores_nothing(client: TestClient, google: FakeGoogle, db_url: str) -> None:
    _, state = start(client, google)
    assert back(client, error="access_denied", state=state) == f"{DONE}cancelled"
    _, state = start(client, google)
    assert back(client, error="server_error", state=state) == f"{DONE}failed"
    assert rows(db_url) == 0


def test_a_code_google_refuses_and_google_down_store_nothing(client: TestClient, google: FakeGoogle,
                                                             db_url: str) -> None:
    _, state = start(client, google)
    assert back(client, code="not-issued", state=state) == f"{DONE}failed"
    code, state = start(client, google)
    google.down = True
    assert back(client, code=code, state=state) == f"{DONE}unavailable"
    assert rows(db_url) == 0


def test_a_state_from_a_connect_cannot_complete_a_discord_link(client: TestClient, google: FakeGoogle) -> None:
    _, state = start(client, google)
    done = client.get("/api/accounts/discord/callback", params={"code": "c", "state": state})
    assert done.headers["location"] == "/connections?link=failed"


def test_connecting_again_under_the_same_label_replaces_the_tokens_and_clears_needs(
        client: TestClient, google: FakeGoogle, db_url: str) -> None:
    connect(client, google, "main")
    with psycopg.connect(db_url) as conn:
        conn.execute("UPDATE connections SET needs = 'reconnect'")
        before = conn.execute("SELECT id, secret, secret_version FROM connections").fetchone()
    assert before is not None and listed(client).connections[0].needs == "reconnect"
    assert connect(client, google, "main") == f"{DONE}connected"
    with psycopg.connect(db_url) as conn:
        after = conn.execute("SELECT id, secret, secret_version, needs FROM connections").fetchall()
    assert [(a[0], a[2], a[3]) for a in after] == [(before[0], before[2] + 1, None)]
    assert bytes(after[0][1]) != bytes(before[1]) and listed(client).connections[0].needs is None


def test_a_second_google_under_another_label_is_too_many(client: TestClient, google: FakeGoogle, db_url: str) -> None:
    connect(client, google, "main")
    assert connect(client, google, "other") == f"{DONE}too_many"
    assert rows(db_url) == 1


def test_start_refuses_what_is_not_an_oauth_kind_of_that_provider_or_not_held_so(client: TestClient,
                                                                               google: FakeGoogle) -> None:
    url = "/api/connections/oauth/google/start"
    assert client.post(url, json={"kind": "sure", "label": ""}, headers=ORIGIN).status_code == 404
    assert client.post(url, json={"kind": "nope", "label": ""}, headers=ORIGIN).status_code == 404
    assert client.post("/api/connections/oauth/other/start", json={"kind": "google", "label": ""},
                       headers=ORIGIN).status_code == 404
    household = client.post(url, json={"kind": "google", "label": "", "holder": "household"}, headers=ORIGIN)
    assert household.status_code == 201
    assert client.post(url, json={"kind": "google", "label": ""}, headers={"origin": "https://evil.test"}
                       ).status_code == 403
    client.cookies.clear()
    assert client.post(url, json={"kind": "google", "label": ""}, headers=ORIGIN).status_code == 401


def test_an_oauth_kind_has_no_secret_to_paste(client: TestClient, google: FakeGoogle) -> None:
    pasted = client.post("/api/connections", json={"kind": "google", "label": "", "token": "x"}, headers=ORIGIN)
    assert pasted.status_code == 422 and pasted.json()["code"] == "unsupported"
    connect(client, google)
    cid = listed(client).connections[0].id
    put = client.put(f"/api/connections/{cid}", json={"token": "x"}, headers=ORIGIN)
    assert put.status_code == 422


def test_the_listing_says_how_a_kind_connects_and_whether_it_is_set_up(client: TestClient) -> None:
    offered = {k.name: k for k in listed(client).offered}
    assert (offered["google"].connect, offered["google"].set_up) == ("oauth", True)
    assert (offered["sure"].connect, offered["sure"].set_up) == ("pasted", True)


def test_unset_starting_is_503_and_the_listing_says_not_set_up(client: TestClient, google: FakeGoogle) -> None:
    services.unregister(OAuthProviders)
    started = client.post("/api/connections/oauth/google/start", json={"kind": "google", "label": ""}, headers=ORIGIN)
    assert started.status_code == 503 and started.json()["code"] == "unavailable"
    assert {k.name: k.set_up for k in listed(client).offered}["google"] is False


def test_nothing_secret_is_logged(client: TestClient, google: FakeGoogle, capsys: pytest.CaptureFixture[str]) -> None:
    capsys.readouterr()
    code, state = start(client, google)
    back(client, code=code, state=state)
    out = capsys.readouterr().out
    assert "connections.connected" in out and "connections.oauth_started" in out
    for secret in (code, state, *google.refresh_tokens, *google.access_tokens):
        assert secret not in out


def test_a_connection_lists_the_scopes_its_person_unticked(client: TestClient, google: FakeGoogle) -> None:
    assert connect(client, google, "main") == f"{DONE}connected"
    assert [c.missing_scopes for c in listed(client).connections] == [[]]
    google.granted = "openid"
    assert connect(client, google, "main") == f"{DONE}connected"
    assert [c.missing_scopes for c in listed(client).connections] == [["email", "https://www.googleapis.com/auth/gmail.modify"]]
