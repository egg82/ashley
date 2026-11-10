"""Blind contract tests for the web push routes (`GET /api/push/key`, `POST /api/push/subscriptions`, `POST
/api/push/subscriptions/find`, `DELETE /api/push/subscriptions`), written from `api/models.py`, `openapi.json` and
decisions.md ("Web push") alone. The fakes behind the locator are in `web_push_support`."""

from typing import Any

import pytest
from ashley import logs
from ashley.api.models import ErrorResponse, PushKeyResponse, PushStateResponse
from web_chat_support import ALANA, COOKIE, ELLA, HOME, JSON, PUBLIC
from web_push_support import (FCM, MARK, MOZILLA, OTHER_PRIVATE, PUBLIC_KEY, SUBJECT, World, body, browser, build,
                              endpoint, keys, settings, world as world)

ROUTES = [("GET", "/api/push/key"), ("POST", "/api/push/subscriptions"), ("POST", "/api/push/subscriptions/find"),
          ("DELETE", "/api/push/subscriptions")]
WRITES = ROUTES[1:]
APPLE = "https://web.push.apple.com/"
WINDOWS = "https://wns2-par02p.notify.windows.com/w/?token="


def payload(method: str, n: int = 1) -> dict[str, Any] | None:
    if method == "GET":
        return None
    return body(n)


def state(got: Any) -> PushStateResponse:
    return PushStateResponse.model_validate(got.json())


def error_of(got: Any) -> ErrorResponse:
    return ErrorResponse.model_validate(got.json())


# ---- GET /api/push/key ----------------------------------------------------------------------------------------

def test_the_key_is_her_vapid_public_key(world: World) -> None:
    got = world.call("GET", "/api/push/key")
    assert got.status_code == 200
    assert PushKeyResponse.model_validate(got.json()).public_key == PUBLIC_KEY


# ---- subscribing ---------------------------------------------------------------------------------------------------

def test_subscribing_is_201_and_stores_that_browser_for_the_signed_in_person(world: World) -> None:
    sent = body(1)
    got = world.call("POST", "/api/push/subscriptions", ALANA, sent)
    assert got.status_code == 201
    assert state(got) == PushStateResponse(subscriptions=1, this_browser=True)
    (row,) = world.subs.rows
    assert (row.household_id, row.person_id) == (HOME, ALANA.id)
    assert (row.browser.endpoint, row.browser.p256dh, row.browser.auth) == (
        sent["endpoint"], sent["keys"]["p256dh"], sent["keys"]["auth"])


def test_the_person_is_the_signed_in_one_whatever_the_body_says(world: World) -> None:
    got = world.call("POST", "/api/push/subscriptions", ELLA, {**body(1), "person_id": ALANA.id, "person": ALANA.id})
    assert got.status_code == 201
    assert world.subs.endpoints(ELLA.id) == [endpoint(1)]
    assert world.subs.endpoints(ALANA.id) == []


def test_a_second_browser_is_counted_and_the_first_kept(world: World) -> None:
    world.call("POST", "/api/push/subscriptions", ALANA, body(1))
    got = world.call("POST", "/api/push/subscriptions", ALANA, body(2, MOZILLA))
    assert state(got) == PushStateResponse(subscriptions=2, this_browser=True)
    assert world.subs.endpoints(ALANA.id) == [endpoint(1), endpoint(2, MOZILLA)]


def test_subscribing_an_endpoint_someone_else_had_moves_it(world: World) -> None:
    world.call("POST", "/api/push/subscriptions", ALANA, body(1))
    new = body(1)
    got = world.call("POST", "/api/push/subscriptions", ELLA, new)
    assert state(got) == PushStateResponse(subscriptions=1, this_browser=True)
    assert world.subs.endpoints(ALANA.id) == []
    assert world.subs.endpoints(ELLA.id) == [endpoint(1)]
    assert world.subs.rows[0].browser.p256dh == new["keys"]["p256dh"]


def test_subscribing_twice_is_one_browser(world: World) -> None:
    world.call("POST", "/api/push/subscriptions", ALANA, body(1))
    got = world.call("POST", "/api/push/subscriptions", ALANA, body(1))
    assert state(got) == PushStateResponse(subscriptions=1, this_browser=True)
    assert len(world.subs.rows) == 1


def test_the_extra_fields_a_browser_sends_are_ignored(world: World) -> None:
    got = world.call("POST", "/api/push/subscriptions", ALANA, {**body(1), "expirationTime": None})
    assert got.status_code == 201


@pytest.mark.parametrize("base", [FCM, MOZILLA, APPLE, WINDOWS])
def test_a_browser_vendors_push_service_is_accepted(world: World, base: str) -> None:
    assert world.call("POST", "/api/push/subscriptions", ALANA, body(1, base)).status_code == 201


@pytest.mark.parametrize("url", [
    "https://evil.example/push/abc",
    "https://127.0.0.1/push/abc",
    "https://localhost/push/abc",
    "http://fcm.googleapis.com/fcm/send/abc",
    "https://fcm.googleapis.com.evil.example/fcm/send/abc",
    "https://evil.example/fcm.googleapis.com/fcm/send/abc",
    "https://evil.example/?next=https://fcm.googleapis.com/",
    "https://xpush.apple.com/abc",
    "https://user:secret@fcm.googleapis.com/fcm/send/abc",
    "https://evil.example@fcm.googleapis.com@evil.example/abc",
    "https://fcm.googleapis.com:8443/fcm/send/abc",
    "https://updates.push.services.mozilla.com.evil.example/wpush/v2/abc",
    "fcm.googleapis.com/fcm/send/abc",
    "",
])
def test_an_endpoint_that_is_not_a_browser_push_service_is_422_and_stores_nothing(world: World, url: str) -> None:
    for method, path in WRITES:
        got = world.call(method, path, ALANA, {"endpoint": url, "keys": keys()} if method == "POST" and path.endswith(
            "subscriptions") else {"endpoint": url})
        assert got.status_code == 422, (method, path)
    assert world.subs.rows == []


@pytest.mark.parametrize("sent", [
    {}, {"endpoint": endpoint(1)}, {"keys": keys()}, {"endpoint": endpoint(1), "keys": {}},
    {"endpoint": endpoint(1), "keys": {"p256dh": "x", "auth": "y"}},
    {"endpoint": endpoint(1), "keys": {**keys(), "extra": "z"}},
    {"endpoint": endpoint(1), "keys": {"p256dh": "not base64url! " * 6, "auth": keys()["auth"]}},
    {"endpoint": 5, "keys": keys()},
])
def test_a_body_that_is_not_a_subscription_is_422_and_stores_nothing(world: World, sent: dict[str, Any]) -> None:
    assert world.call("POST", "/api/push/subscriptions", ALANA, sent).status_code == 422
    assert world.subs.rows == []


@pytest.mark.parametrize("path", ["/api/push/subscriptions/find"])
def test_find_and_delete_bodies_hold_an_endpoint_and_nothing_else(world: World, path: str) -> None:
    assert world.call("POST", path, ALANA, {"endpoint": endpoint(1), "keys": keys()}).status_code == 422
    assert world.call("POST", path, ALANA, {}).status_code == 422
    assert world.call("DELETE", "/api/push/subscriptions", ALANA, {"endpoint": endpoint(1), "x": 1}).status_code == 422


# ---- finding -------------------------------------------------------------------------------------------------------

def test_find_says_whether_this_browser_is_the_persons_and_how_many_they_have(world: World) -> None:
    world.call("POST", "/api/push/subscriptions", ALANA, body(1))
    world.call("POST", "/api/push/subscriptions", ALANA, body(2))
    mine = world.call("POST", "/api/push/subscriptions/find", ALANA, {"endpoint": endpoint(1)})
    assert mine.status_code == 200
    assert state(mine) == PushStateResponse(subscriptions=2, this_browser=True)
    unknown = world.call("POST", "/api/push/subscriptions/find", ALANA, {"endpoint": endpoint(9)})
    assert state(unknown) == PushStateResponse(subscriptions=2, this_browser=False)


def test_a_browser_that_is_someone_elses_is_not_found_for_this_person(world: World) -> None:
    world.call("POST", "/api/push/subscriptions", ALANA, body(1))
    got = world.call("POST", "/api/push/subscriptions/find", ELLA, {"endpoint": endpoint(1)})
    assert state(got) == PushStateResponse(subscriptions=0, this_browser=False)


def test_find_changes_nothing(world: World) -> None:
    world.call("POST", "/api/push/subscriptions", ALANA, body(1))
    before = list(world.subs.rows)
    world.call("POST", "/api/push/subscriptions/find", ALANA, {"endpoint": endpoint(1)})
    world.call("POST", "/api/push/subscriptions/find", ELLA, {"endpoint": endpoint(1)})
    assert world.subs.rows == before


def test_finding_is_a_post_so_the_endpoint_never_goes_in_a_url(world: World) -> None:
    assert world.call("GET", "/api/push/subscriptions/find", ALANA).status_code == 405


# ---- unsubscribing -------------------------------------------------------------------------------------------------

def test_deleting_removes_this_browser_and_says_so(world: World) -> None:
    world.call("POST", "/api/push/subscriptions", ALANA, body(1))
    world.call("POST", "/api/push/subscriptions", ALANA, body(2))
    got = world.call("DELETE", "/api/push/subscriptions", ALANA, {"endpoint": endpoint(1)})
    assert got.status_code == 200
    assert state(got) == PushStateResponse(subscriptions=1, this_browser=False)
    assert world.subs.endpoints(ALANA.id) == [endpoint(2)]


def test_deleting_an_endpoint_that_is_someone_elses_changes_nothing(world: World) -> None:
    world.call("POST", "/api/push/subscriptions", ALANA, body(1))
    got = world.call("DELETE", "/api/push/subscriptions", ELLA, {"endpoint": endpoint(1)})
    assert got.status_code == 200
    assert state(got) == PushStateResponse(subscriptions=0, this_browser=False)
    assert world.subs.endpoints(ALANA.id) == [endpoint(1)]


def test_deleting_an_endpoint_nobody_has_is_200_and_changes_nothing(world: World) -> None:
    world.call("POST", "/api/push/subscriptions", ALANA, body(1))
    got = world.call("DELETE", "/api/push/subscriptions", ALANA, {"endpoint": endpoint(7)})
    assert state(got) == PushStateResponse(subscriptions=1, this_browser=False)


# ---- who may ask ---------------------------------------------------------------------------------------------------

@pytest.mark.parametrize(("method", "path"), ROUTES)
def test_no_session_is_401_unauthorized_and_stores_nothing(world: World, method: str, path: str) -> None:
    got = world.call(method, path, None, payload(method))
    assert got.status_code == 401
    assert error_of(got).code == "unauthorized"
    assert world.subs.rows == []


@pytest.mark.parametrize(("method", "path"), ROUTES)
def test_a_token_that_is_no_session_is_401(world: World, method: str, path: str) -> None:
    got = world.app.request(method, path, json=payload(method), headers={**JSON, "cookie": f"{COOKIE}=t-999"})
    assert got.status_code == 401


@pytest.mark.parametrize(("method", "path"), WRITES)
def test_a_request_from_another_site_is_403_forbidden_and_changes_nothing(world: World, method: str, path: str) -> None:
    world.subs.seed(ALANA, browser(1))
    before = list(world.subs.rows)
    got = world.call(method, path, ALANA, payload_for(path, method), {"origin": "https://evil.example"})
    assert got.status_code == 403
    assert error_of(got).code == "forbidden"
    assert world.subs.rows == before


@pytest.mark.parametrize(("method", "path"), WRITES)
def test_a_body_that_is_not_json_is_403_forbidden_and_changes_nothing(world: World, method: str, path: str) -> None:
    got = world.app.request(method, path, content=str(payload_for(path, method)),
                            headers={"content-type": "text/plain", "origin": PUBLIC, "cookie": f"{COOKIE}=t-1"})
    assert got.status_code == 403
    assert error_of(got).code == "forbidden"
    assert world.subs.rows == []


def payload_for(path: str, method: str) -> dict[str, Any]:
    return body(1) if method == "POST" and path.endswith("subscriptions") else {"endpoint": endpoint(1)}


# ---- not set up ----------------------------------------------------------------------------------------------------

def _not_set_up() -> list[Any]:
    other = {"vapid_private_key": OTHER_PRIVATE}
    return [pytest.param({"vapid_public_key": "", "vapid_private_key": "", "vapid_subject": ""}, id="unset"),
            pytest.param({"vapid_private_key": ""}, id="no-private-key"),
            pytest.param({"vapid_public_key": ""}, id="no-public-key"),
            pytest.param({"vapid_subject": ""}, id="no-subject"),
            pytest.param(other, id="keys-of-two-pairs"),
            pytest.param({"vapid_private_key": "nonsense"}, id="private-key-not-a-key")]


@pytest.mark.parametrize("changes", _not_set_up())
def test_without_one_key_pair_every_route_is_503_unavailable(changes: dict[str, str]) -> None:
    for made in build(settings(**changes), wired=False):
        for method, path in ROUTES:
            got = made.call(method, path, ALANA, payload_for(path, method) if method != "GET" else None)
            assert got.status_code == 503, (method, path)
            assert error_of(got).code == "unavailable"
        assert made.subs.rows == []


@pytest.mark.parametrize(("method", "path"), WRITES)
def test_subscriptions_that_cannot_be_reached_is_503_unavailable(world: World, method: str, path: str) -> None:
    world.subs.down = True
    got = world.call(method, path, ALANA, payload_for(path, method))
    assert got.status_code == 503
    assert error_of(got).code == "unavailable"


# ---- logs ----------------------------------------------------------------------------------------------------------

def test_logs_carry_no_endpoint_and_no_keys(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    sent = body(1)
    world.call("POST", "/api/push/subscriptions", ALANA, sent)
    world.call("POST", "/api/push/subscriptions/find", ALANA, {"endpoint": sent["endpoint"]})
    world.call("DELETE", "/api/push/subscriptions", ALANA, {"endpoint": sent["endpoint"]})
    world.call("POST", "/api/push/subscriptions", ALANA, {"endpoint": "https://evil.example/" + MARK, "keys": sent["keys"]})
    world.subs.down = True
    world.call("POST", "/api/push/subscriptions", ALANA, body(2))
    out = capsys.readouterr().out + capsys.readouterr().err
    for secret in (sent["endpoint"], sent["keys"]["p256dh"], sent["keys"]["auth"], MARK, "evil.example", SUBJECT):
        assert secret not in out
