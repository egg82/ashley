"""The scopes Google says it granted are stored with the connection, and a scope not granted is reported."""

from fastapi.testclient import TestClient
from mail_oauth_blind_fake_support import FakeGoogle
from mail_oauth_blind_support import SCOPES, connect, the_google


def test_the_granted_scopes_are_stored_and_none_is_missing(client: TestClient, fake: FakeGoogle) -> None:
    assert connect(client, fake) == "connected"
    shown = the_google(client)
    assert sorted(shown["scopes"]) == sorted(SCOPES) and shown["missing_scopes"] == []


def test_a_scope_the_person_unticked_is_missing_and_the_connection_is_still_stored(
        client: TestClient, fake: FakeGoogle) -> None:
    fake.grant_scopes = ("openid",)
    fake.always_email = True
    assert connect(client, fake) == "connected"
    shown = the_google(client)
    assert shown["scopes"] == ["openid"] and shown["missing_scopes"] == ["email", "https://www.googleapis.com/auth/gmail.modify"]


def test_the_scopes_stored_are_the_ones_google_answered_not_the_ones_asked(client: TestClient, fake: FakeGoogle) -> None:
    fake.grant_scopes = ("openid", "email", "https://www.googleapis.com/auth/gmail.modify", "https://www.googleapis.com/auth/userinfo.profile")
    assert connect(client, fake) == "connected"
    shown = the_google(client)
    assert "https://www.googleapis.com/auth/userinfo.profile" in shown["scopes"]
    assert shown["missing_scopes"] == []


def test_a_reconnect_with_a_wider_grant_replaces_the_stored_scopes(client: TestClient, fake: FakeGoogle) -> None:
    fake.grant_scopes = ("openid",)
    fake.always_email = True
    connect(client, fake)
    fake.grant_scopes = None
    assert connect(client, fake) == "connected"
    shown = the_google(client)
    assert sorted(shown["scopes"]) == sorted(SCOPES) and shown["missing_scopes"] == []
