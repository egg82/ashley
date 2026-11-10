"""Tokens, codes, states, verifiers and the client secret never reach a log line, a response, or a stored column in the
clear."""

import logging

import pytest
from ashley.connections.oauth import OAuthUnavailable
from ashley.connections.renewal import NeedsReconnect
from fastapi.testclient import TestClient
from mail_oauth_blind_fake_support import DAY, FakeGoogle, carries
from mail_oauth_blind_support import (People, all_logs, back, begin, connected, fresh, listed, log_text, row_text,
                                      start)


def swallow(client: TestClient, people: People, cid: int) -> None:
    try:
        fresh(client, people, cid)
    except (NeedsReconnect, OAuthUnavailable):
        pass


def test_no_log_line_carries_a_token_a_code_a_state_a_verifier_or_the_client_secret(
        client: TestClient, fake: FakeGoogle, people: People, caplog: pytest.LogCaptureFixture) -> None:
    all_logs(caplog)
    fake.expires_in = 1
    cid, _, _ = connected(client, fake, people)
    fake.rotate = True
    fresh(client, people, cid)
    fake.refresh_down = True
    swallow(client, people, cid)
    fake.refresh_down = False
    fake.refuse_refresh = True
    swallow(client, people, cid)
    fake.refuse_refresh = False
    states: set[str] = set()
    fake.userinfo = "unauthorized"
    code, state = start(client, fake)
    states.add(state)
    back(client, code=code, state=state)
    fake.refuse_code = True
    code, state = start(client, fake)
    states.add(state)
    back(client, code=code, state=state)
    text = log_text(caplog)
    assert fake.secret_values() and text
    leaked = sorted(v for v in fake.secret_values() | states if v in text)
    assert not leaked, leaked


def test_the_connect_and_the_renewal_each_leave_a_log_line(client: TestClient, fake: FakeGoogle, people: People,
                                                           caplog: pytest.LogCaptureFixture) -> None:
    all_logs(caplog)
    fake.expires_in = 1
    cid, _, _ = connected(client, fake, people)
    connected_lines = len([r for r in caplog.records if r.levelno >= logging.INFO and r.name.startswith("ashley")])
    fake.expires_in = DAY
    fresh(client, people, cid)
    renewed_lines = len([r for r in caplog.records if r.levelno >= logging.INFO and r.name.startswith("ashley")])
    assert connected_lines > 0 and renewed_lines > connected_lines


def test_a_refusal_to_renew_is_logged(client: TestClient, fake: FakeGoogle, people: People,
                                      caplog: pytest.LogCaptureFixture) -> None:
    fake.expires_in = 1
    cid, _, _ = connected(client, fake, people)
    caplog.clear()
    all_logs(caplog)
    fake.refuse_refresh = True
    swallow(client, people, cid)
    assert [r for r in caplog.records if r.levelno >= logging.WARNING and r.name.startswith("ashley")]


def test_nothing_stored_holds_a_token_in_the_clear(client: TestClient, fake: FakeGoogle, people: People,
                                                   db_url: str) -> None:
    fake.expires_in = 1
    cid, refresh, access = connected(client, fake, people)
    fake.rotate = True
    fresh(client, people, cid)
    begin(client)
    stored = row_text(db_url)
    assert stored.strip()
    for secret in (refresh, access, *fake.issued_access, *fake.issued_refresh):
        assert not carries(stored, secret), secret


def test_no_response_carries_a_token_or_the_verifier(client: TestClient, fake: FakeGoogle, people: People) -> None:
    started = begin(client)
    code, state = fake.authorize(started.json()["authorize_url"])
    back_to = client.get("/api/connections/oauth/google/callback", params={"code": code, "state": state})
    seen = [started.text, back_to.headers["location"], client.get("/api/connections").text]
    for secret in fake.secret_values() - {code}:
        assert not any(secret in text for text in seen), secret
    assert listed(client)


def test_the_client_secret_is_sent_to_the_token_endpoint_only(client: TestClient, fake: FakeGoogle,
                                                              people: People) -> None:
    connected(client, fake, people)
    for s in fake.seen:
        if s.kind != "token":
            assert not any("CLIENTSECRET" in v for v in (*s.form.values(), s.bearer, s.path))
