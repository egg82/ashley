"""Renewing a Google connection's access token against the real app, a real database and Google faked at its HTTP
boundary: a fresh token is reused without a refresh; a stale one is refreshed once and stored; two pods refreshing at
once leave one current secret and both answer (the loser reads the winner's token); a refused refresh marks the
connection `reconnect` and keeps the row; a connection marked so is not retried."""

from collections.abc import Awaitable, Callable
from typing import Any

import psycopg
import pytest
from ashley import services
from ashley.connections.model import Grant
from ashley.connections.oauth import OAuthProvider, OAuthProviders, OAuthRefused, OAuthUnavailable
from ashley.connections.oauth_connections import OAuthConnections
from ashley.connections.renewal import NeedsReconnect, Renewal
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from fastapi.testclient import TestClient
from oauth_google_support import FakeGoogle
from oauth_home_support import Home, client as client, connect, google as google, home as home


def run(client: TestClient, call: Callable[..., Awaitable[Any]], *args: Any) -> Any:
    portal = client.portal
    assert portal is not None
    return portal.call(call, *args)


def expire(db_url: str, seconds: int) -> None:
    with psycopg.connect(db_url) as conn:
        conn.execute("UPDATE connections SET access_expires_at = now() + make_interval(secs => %s)", (seconds,))


def row(db_url: str) -> tuple[int, str | None]:
    with psycopg.connect(db_url) as conn:
        found = conn.execute("SELECT secret_version, needs FROM connections").fetchone()
    assert found is not None
    return found


def ids(db_url: str) -> int:
    with psycopg.connect(db_url) as conn:
        found = conn.execute("SELECT id FROM connections").fetchone()
    assert found is not None
    return int(found[0])


def token(client: TestClient, db_url: str, home: Home, person: int | None = None) -> str | None:
    return run(client, services.get(Renewal).access_token, ids(db_url), home.household, person or home.alana)


def stored(client: TestClient, db_url: str, home: Home) -> Any:
    return run(client, services.get(OAuthConnections).state, ids(db_url), home.household, home.alana)


@pytest.fixture
def connected(client: TestClient, google: FakeGoogle) -> None:
    connect(client, google, "main")


def test_a_fresh_token_is_reused_without_asking_google(client: TestClient, google: FakeGoogle, home: Home,
                                                      db_url: str, connected: None) -> None:
    first = token(client, db_url, home)
    assert first in google.access_tokens and token(client, db_url, home) == first
    assert google.calls("refresh_token") == 0 and row(db_url) == (1, None)


def test_a_token_within_the_margin_is_refreshed_once_and_stored(client: TestClient, google: FakeGoogle, home: Home,
                                                               db_url: str, connected: None) -> None:
    old = stored(client, db_url, home).access_token
    expire(db_url, 60)
    new = token(client, db_url, home)
    assert new is not None and new != old and new in google.access_tokens
    assert token(client, db_url, home) == new
    state = stored(client, db_url, home)
    assert google.calls("refresh_token") == 1 and state.access_token == new and state.version == 2
    assert state.expires_in_s > 3500


def test_a_token_outside_the_margin_is_not_refreshed(client: TestClient, google: FakeGoogle, home: Home, db_url: str,
                                                    connected: None) -> None:
    expire(db_url, 900)
    token(client, db_url, home)
    assert google.calls("refresh_token") == 0


def test_a_rotated_refresh_token_is_stored_and_the_next_refresh_uses_it(client: TestClient, google: FakeGoogle,
                                                                       home: Home, db_url: str, connected: None) -> None:
    google.rotate = True
    expire(db_url, 0)
    token(client, db_url, home)
    state = stored(client, db_url, home)
    assert state.opened.secret in google.refresh_tokens and len(google.refresh_tokens) == 1
    expire(db_url, 0)
    assert token(client, db_url, home) is not None and google.calls("refresh_token") == 2


def test_a_refused_refresh_marks_the_connection_and_keeps_it(client: TestClient, google: FakeGoogle, home: Home,
                                                            db_url: str, connected: None,
                                                            capsys: pytest.CaptureFixture[str]) -> None:
    capsys.readouterr()
    google.refresh_tokens.clear()
    expire(db_url, 0)
    with pytest.raises(NeedsReconnect):
        token(client, db_url, home)
    assert row(db_url) == (2, "reconnect")
    assert "event=connections.refresh_refused connection=1 kind=google reason=invalid_grant" in capsys.readouterr().out
    calls = google.calls("refresh_token")
    with pytest.raises(NeedsReconnect):
        token(client, db_url, home)
    assert google.calls("refresh_token") == calls, "a marked connection is not retried"
    assert client.get("/api/connections").json()["connections"][0]["needs"] == "reconnect"


def test_google_down_leaves_the_connection_unmarked(client: TestClient, google: FakeGoogle, home: Home, db_url: str,
                                                   connected: None) -> None:
    expire(db_url, 0)
    google.down = True
    with pytest.raises(OAuthUnavailable):
        token(client, db_url, home)
    assert row(db_url) == (1, None)


def test_another_person_cannot_renew_a_connection_that_is_not_theirs(client: TestClient, home: Home, db_url: str,
                                                                    connected: None) -> None:
    assert token(client, db_url, home, home.sam) is None


class Rival(OAuthProvider):
    """The provider, but another pod stores its own refreshed token between this pod's read and its write."""

    def __init__(self, inner: OAuthProvider, client: TestClient, connection: int, version: int,
                 then: Callable[[], Awaitable[Grant]] | None = None) -> None:
        self.inner, self.client, self.connection, self.version, self.then = inner, client, connection, version, then
        self.rival = Grant("ya29.rival", None, 3600, ())

    async def _rival_writes(self) -> None:
        assert await services.get(OAuthConnections).renewed(self.connection, self.version, self.rival)

    def authorize_url(self, state: str, challenge: str, scopes: tuple[str, ...]) -> str:
        return self.inner.authorize_url(state, challenge, scopes)

    async def redeem(self, code: str, verifier: str) -> Grant:
        return await self.inner.redeem(code, verifier)

    async def refresh(self, refresh_token: str) -> Grant:
        await self._rival_writes()
        if self.then is not None:
            return await self.then()
        return await self.inner.refresh(refresh_token)

    async def check(self, access_token: str) -> Any:
        return await self.inner.check(access_token)


def test_a_pod_that_loses_the_compare_and_set_uses_the_winners_token(client: TestClient, google: FakeGoogle, home: Home,
                                                                   db_url: str, connected: None,
                                                                   capsys: pytest.CaptureFixture[str]) -> None:
    capsys.readouterr()
    expire(db_url, 0)
    rival = Rival(google.provider(), client, ids(db_url), 1)
    services.register(OAuthProviders, OAuthProviders({"google": rival}))
    assert token(client, db_url, home) == "ya29.rival"
    state = stored(client, db_url, home)
    assert state.access_token == "ya29.rival" and state.version == 2 and state.expires_in_s > 3500
    assert "event=connections.refreshed connection=1 kind=google lost_race=true" in capsys.readouterr().out


def test_a_pod_whose_refresh_is_refused_after_a_rival_won_is_not_marked(client: TestClient, google: FakeGoogle,
                                                                       home: Home, db_url: str, connected: None) -> None:
    async def refused() -> Grant:
        raise OAuthRefused("invalid_grant")

    expire(db_url, 0)
    rival = Rival(google.provider(), client, ids(db_url), 1, refused)
    services.register(OAuthProviders, OAuthProviders({"google": rival}))
    assert token(client, db_url, home) == "ya29.rival"
    assert row(db_url) == (2, None)


def test_a_write_at_a_stale_version_changes_nothing(client: TestClient, home: Home, db_url: str,
                                                   connected: None) -> None:
    before = stored(client, db_url, home)
    connections = services.get(OAuthConnections)
    cid = ids(db_url)
    assert run(client, connections.renewed, cid, 99, Grant("late", None, 3600, ())) is False
    assert run(client, connections.needs_reconnect, cid, 99) is False
    after = stored(client, db_url, home)
    assert (after.access_token, after.version, after.opened.connection.needs) == (before.access_token, 1, None)
