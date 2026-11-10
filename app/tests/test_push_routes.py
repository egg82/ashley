"""The push routes through the real app and a real database: a signed-in person reads her public key, subscribes this
browser, finds it, and unsubscribes it; a browser subscribed by another person moves to them; an endpoint off the
browsers' push services is 422 and a cross-site write 403; signed out is 401; with push not configured every route is
503. No endpoint or key is logged."""

import hashlib
import secrets
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass

import psycopg
import pytest
from ashley import services
from ashley.api.person import SESSION_COOKIE
from ashley.channels.push.subscriptions import Subscriptions
from ashley.main import create_app
from ashley.people import admin
from ashley.settings import Settings
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from fastapi.testclient import TestClient
from later_support import Logged
from push_support import AUTH, P256DH, browser, key_pair

PUBLIC = "https://ashley.test"
ORIGIN = {"origin": PUBLIC}
PUBLIC_KEY, PRIVATE_KEY = key_pair()


def _session(conn: psycopg.Connection, account_id: int, household_id: int) -> str:
    token = secrets.token_urlsafe(16)
    conn.execute("INSERT INTO sessions (token_sha256, account_id, household_id, expires_at) "
                 "VALUES (%s, %s, %s, now() + interval '1 day')",
                 (hashlib.sha256(token.encode()).digest(), account_id, household_id))
    return token


@dataclass(frozen=True)
class Home:
    alana_token: str
    sam_token: str


@pytest.fixture
def home(db_url: str) -> Home:
    with psycopg.connect(db_url) as conn:
        hid = admin.add_household(conn, "home", "America/Denver")
        alana, sam = admin.add_person(conn, hid, "Alana"), admin.add_person(conn, hid, "Sam")
        return Home(_session(conn, admin.add_account(conn, alana, "oidc", "sub-alana"), hid),
                    _session(conn, admin.add_account(conn, sam, "oidc", "sub-sam"), hid))


@contextmanager
def _client(db_url: str, token: str, configured: bool) -> Generator[TestClient]:
    """The app as a pod builds it, with or without her VAPID identity; Subscriptions unwired afterwards, since wiring
    registers it only when push is configured."""
    keys = {"vapid_public_key": PUBLIC_KEY, "vapid_private_key": PRIVATE_KEY,
            "vapid_subject": "mailto:admin@example.test"} if configured else {}
    app = create_app(Settings(database_url=db_url, build_version="t", public_url=PUBLIC, **keys))
    try:
        with TestClient(app, base_url=PUBLIC) as c:
            c.cookies.set(SESSION_COOKIE, token, domain="ashley.test")
            yield c
    finally:
        services.unregister(Subscriptions)


@pytest.fixture
def client(db_url: str, home: Home) -> Generator[TestClient]:
    with _client(db_url, home.alana_token, configured=True) as c:
        yield c


def body(n: int = 1) -> dict[str, object]:
    b = browser(n)
    return {"endpoint": b.endpoint, "expirationTime": None, "keys": {"p256dh": b.p256dh, "auth": b.auth}}


def where(n: int = 1) -> dict[str, str]:
    return {"endpoint": browser(n).endpoint}


def test_subscribe_find_and_unsubscribe_this_browser(client: TestClient, capsys: pytest.CaptureFixture[str]) -> None:
    log = Logged(capsys)
    assert client.get("/api/push/key").json() == {"public_key": PUBLIC_KEY}
    assert client.post("/api/push/subscriptions/find", json=where(1), headers=ORIGIN).json() == {
        "subscriptions": 0, "this_browser": False}
    made = client.post("/api/push/subscriptions", json=body(1), headers=ORIGIN)
    assert made.status_code == 201 and made.json() == {"subscriptions": 1, "this_browser": True}
    client.post("/api/push/subscriptions", json=body(2), headers=ORIGIN)
    assert client.post("/api/push/subscriptions/find", json=where(1), headers=ORIGIN).json() == {
        "subscriptions": 2, "this_browser": True}
    gone = client.request("DELETE", "/api/push/subscriptions", json=where(1), headers=ORIGIN)
    assert gone.status_code == 200 and gone.json() == {"subscriptions": 1, "this_browser": False}
    assert [e["subscriptions"] for e in log.events("push.subscribed")] == ["1", "2"]
    text = log.read()
    assert "fcm.googleapis.com" not in text and P256DH not in text and AUTH not in text


def test_a_browser_subscribed_by_another_person_moves_to_them(db_url: str, home: Home, client: TestClient) -> None:
    client.post("/api/push/subscriptions", json=body(1), headers=ORIGIN)
    client.cookies.set(SESSION_COOKIE, home.sam_token, domain="ashley.test")
    assert client.post("/api/push/subscriptions", json=body(1), headers=ORIGIN).json() == {
        "subscriptions": 1, "this_browser": True}
    client.cookies.set(SESSION_COOKIE, home.alana_token, domain="ashley.test")
    assert client.post("/api/push/subscriptions/find", json=where(1), headers=ORIGIN).json() == {
        "subscriptions": 0, "this_browser": False}


def test_unsubscribing_someone_elses_browser_changes_nothing(db_url: str, home: Home, client: TestClient) -> None:
    client.post("/api/push/subscriptions", json=body(1), headers=ORIGIN)
    client.cookies.set(SESSION_COOKIE, home.sam_token, domain="ashley.test")
    assert client.request("DELETE", "/api/push/subscriptions", json=where(1), headers=ORIGIN).json() == {
        "subscriptions": 0, "this_browser": False}
    client.cookies.set(SESSION_COOKIE, home.alana_token, domain="ashley.test")
    assert client.post("/api/push/subscriptions/find", json=where(1), headers=ORIGIN).json()["this_browser"] is True


@pytest.mark.parametrize("endpoint", ["https://evil.example/push", "http://fcm.googleapis.com/fcm/send/x",
                                      "https://10.0.0.1/x"])
def test_an_endpoint_off_the_push_services_is_refused(client: TestClient, endpoint: str) -> None:
    sent = {**body(1), "endpoint": endpoint}
    assert client.post("/api/push/subscriptions", json=sent, headers=ORIGIN).status_code == 422
    assert client.post("/api/push/subscriptions/find", json={"endpoint": endpoint}, headers=ORIGIN).status_code == 422


def test_a_cross_site_write_is_forbidden_and_signed_out_is_unauthorized(client: TestClient) -> None:
    assert client.post("/api/push/subscriptions", json=body(1),
                       headers={"origin": "https://evil.example"}).status_code == 403
    client.cookies.clear()
    assert client.get("/api/push/key").status_code == 401
    assert client.post("/api/push/subscriptions", json=body(1), headers=ORIGIN).status_code == 401


def test_with_push_not_configured_every_route_is_unavailable(db_url: str, home: Home) -> None:
    with _client(db_url, home.alana_token, configured=False) as off:
        answers = [off.get("/api/push/key"), off.post("/api/push/subscriptions", json=body(1), headers=ORIGIN),
                   off.post("/api/push/subscriptions/find", json=where(1), headers=ORIGIN),
                   off.request("DELETE", "/api/push/subscriptions", json=where(1), headers=ORIGIN)]
    assert [(a.status_code, a.json()["code"]) for a in answers] == [(503, "unavailable")] * 4
