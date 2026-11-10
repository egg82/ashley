"""Blind contract tests for the hallway tablet, from `api/models.py`, `openapi.json` and decisions.md alone: pairing, the
device token checked on every request, public traffic, same-origin writes, and the two kinds of cookie never crossing.
The fakes are in `kiosk_support`."""

from typing import Any

import pytest
from ashley.api.models import KioskDevice
from kiosk_support import (ALANA, DEVICE, ELLA, HALL_LIGHT, KIOSK_COOKIE, PUBLIC, TOKEN, TWELVE, Kiosk, call,
                           cookie_routes, kiosk as kiosk, kiosk_routes, person_cookie, reads)
from web_chat_support import JSON, error_of


EVIL = {"origin": "https://evil.test"}


# ---- POST /api/kiosk/session -------------------------------------------------------------------------------------

def test_a_device_token_pairs_the_screen_as_that_device(kiosk: Kiosk) -> None:
    got = kiosk.post("/api/kiosk/session", {"token": TOKEN}, token=None)
    assert got.status_code == 200
    assert KioskDevice.model_validate(got.json()) == KioskDevice(id=DEVICE.id, name=DEVICE.name, place=DEVICE.place)
    assert kiosk.devices.asked == [TOKEN]


def test_the_session_sets_the_kiosk_cookie_secure_httponly_and_strict(kiosk: Kiosk) -> None:
    got = kiosk.post("/api/kiosk/session", {"token": TOKEN}, token=None)
    (cookie,) = [v for k, v in got.headers.multi_items() if k.lower() == "set-cookie"]
    attributes = [a.strip().lower() for a in cookie.split(";")]
    assert attributes[0].startswith(f"{KIOSK_COOKIE.lower()}=")
    assert {"secure", "httponly", "samesite=strict"} <= set(attributes)
    assert "path=/" in attributes and not any(a.startswith("domain") for a in attributes)


def test_the_cookie_the_session_set_is_enough_to_use_the_kiosk(kiosk: Kiosk) -> None:
    kiosk.app.post("/api/kiosk/session", json={"token": TOKEN}, headers=JSON)
    assert kiosk.app.get("/api/kiosk/device").status_code == 200
    assert KioskDevice.model_validate(kiosk.app.get("/api/kiosk/device").json()).id == DEVICE.id


@pytest.mark.parametrize("token", ["wrong", "x" * 200, " ", "../etc"])
def test_a_token_that_signs_in_no_device_is_401_and_sets_no_cookie(kiosk: Kiosk, token: str) -> None:
    got = kiosk.post("/api/kiosk/session", {"token": token}, token=None)
    assert got.status_code == 401
    assert error_of(got).code == "unauthorized"
    assert "set-cookie" not in got.headers


@pytest.mark.parametrize("body", [{}, {"token": ""}, {"token": "x" * 201}, {"token": TOKEN, "extra": 1}, {"token": 5}])
def test_a_body_that_is_not_a_pairing_request_is_422_and_sets_no_cookie(kiosk: Kiosk, body: dict[str, Any]) -> None:
    got = kiosk.post("/api/kiosk/session", body, token=None)
    assert got.status_code == 422
    assert "set-cookie" not in got.headers


def test_pairing_with_the_device_store_down_is_503(kiosk: Kiosk) -> None:
    kiosk.devices.down = True
    got = kiosk.post("/api/kiosk/session", {"token": TOKEN}, token=None)
    assert got.status_code == 503
    assert error_of(got).code == "unavailable"
    assert "set-cookie" not in got.headers


def test_pairing_is_not_counted_against_the_rate(kiosk: Kiosk) -> None:
    kiosk.post("/api/kiosk/session", {"token": TOKEN}, token=None)
    assert kiosk.devices.counted == []


# ---- the screen is a device, checked on every request ----------------------------------------------------------------

@pytest.mark.parametrize("path", reads())
def test_every_read_checks_the_token_in_the_cookie_each_time(kiosk: Kiosk, path: str) -> None:
    assert kiosk.get(path).status_code == 200
    assert kiosk.get(path).status_code == 200
    assert kiosk.devices.asked == [TOKEN, TOKEN]


@pytest.mark.parametrize("method,path", cookie_routes())
def test_a_revoked_device_unpairs_the_screen_on_every_route(kiosk: Kiosk, method: str, path: str) -> None:
    assert call(kiosk, method, path).status_code != 401
    kiosk.devices.by.clear()
    got = call(kiosk, method, path)
    assert got.status_code == 401 and error_of(got).code == "unauthorized"
    assert kiosk.effects()[:2] == (1 if path.endswith("messages") else 0, 1 if "controls/" in path else 0)


@pytest.mark.parametrize("method,path", cookie_routes())
def test_no_cookie_and_a_wrong_cookie_are_401_on_every_route(kiosk: Kiosk, method: str, path: str) -> None:
    for token in (None, "wrong", ""):
        got = call(kiosk, method, path, token=token)
        assert got.status_code == 401 and error_of(got).code == "unauthorized"
    assert kiosk.effects() == (0, 0, 0)


@pytest.mark.parametrize("method,path", kiosk_routes())
def test_the_devices_store_down_is_503_on_every_route(kiosk: Kiosk, method: str, path: str) -> None:
    kiosk.devices.down = True
    got = call(kiosk, method, path)
    assert got.status_code == 503 and error_of(got).code == "unavailable"
    assert kiosk.effects() == (0, 0, 0)


# ---- public traffic ----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("method,path", kiosk_routes())
def test_a_request_carrying_cf_connecting_ip_is_401_on_every_route(kiosk: Kiosk, method: str, path: str) -> None:
    got = call(kiosk, method, path, headers={"Cf-Connecting-IP": "203.0.113.9"})
    assert got.status_code == 401 and error_of(got).code == "unauthorized"
    assert "set-cookie" not in got.headers
    assert kiosk.effects() == (0, 0, 0)


@pytest.mark.parametrize("value", ["", "203.0.113.9"])
def test_the_header_refuses_pairing_even_with_a_good_token_and_even_empty(kiosk: Kiosk, value: str) -> None:
    got = kiosk.post("/api/kiosk/session", {"token": TOKEN}, headers={"cf-connecting-ip": value}, token=None)
    assert got.status_code == 401
    assert "set-cookie" not in got.headers


# ---- same-origin JSON writes -------------------------------------------------------------------------------------

BAD_WRITES = [{"origin": "https://evil.test"}, {"origin": "http://ashley.test"}, {"origin": "", "sec-fetch-site": "cross-site"},
              {"content-type": "text/plain"}, {"content-type": "application/x-www-form-urlencoded"}]


def write_cases() -> list[Any]:
    cases: list[Any] = []
    for path in ("/api/kiosk/messages", f"/api/kiosk/controls/{HALL_LIGHT.id}", "/api/kiosk/session"):
        for headers in BAD_WRITES:
            cases.append(pytest.param(path, headers))
    return cases


@pytest.mark.parametrize("path,headers", write_cases())
def test_a_cross_origin_or_non_json_write_is_403_and_does_nothing(kiosk: Kiosk, path: str,
                                                                  headers: dict[str, str]) -> None:
    sent = {**JSON, **kiosk.cookie(TOKEN), **headers}
    if headers.get("origin") == "":
        del sent["origin"]
    body = f'{{"token": "{TOKEN}"}}' if path.endswith("session") else '{"text": "hi"}'
    got = kiosk.app.post(path, content=body.encode(), headers=sent)
    assert got.status_code == 403 and error_of(got).code == "forbidden"
    assert "set-cookie" not in got.headers
    assert kiosk.effects() == (0, 0, 0)


def test_a_same_origin_json_write_is_accepted(kiosk: Kiosk) -> None:
    assert kiosk.post("/api/kiosk/messages", {"text": "hi"}, headers={"origin": PUBLIC}).status_code == 200


# ---- the two kinds of cookie never cross -----------------------------------------------------------------------------

@pytest.mark.parametrize("method,path", cookie_routes())
def test_a_persons_session_cookie_never_works_on_a_kiosk_route(kiosk: Kiosk, method: str, path: str) -> None:
    for person in (ALANA, ELLA, TWELVE):
        got = call(kiosk, method, path, token=None, headers=person_cookie(person.id))
        assert got.status_code == 401
        # a person's session token offered as the kiosk cookie, or both cookies at once
        offered = call(kiosk, method, path, token=f"t-{person.id}", headers=person_cookie(person.id))
        assert offered.status_code == 401
    assert kiosk.effects() == (0, 0, 0)


PERSON_ROUTES = [("GET", "/api/me"), ("GET", "/api/memory/facts"), ("GET", "/api/chat/conversation"),
                 ("POST", "/api/chat/messages")]


@pytest.mark.parametrize("method,path", PERSON_ROUTES)
def test_the_kiosk_cookie_never_works_on_a_persons_route(kiosk: Kiosk, method: str, path: str) -> None:
    body = {"text": "hi"} if "messages" in path else None
    sent = kiosk.app.request(method, path, json=body, headers={**JSON, **kiosk.cookie(TOKEN)})
    assert sent.status_code == 401 and error_of(sent).code == "unauthorized"
    session_named = kiosk.app.request(method, path, json=body, headers={**JSON, "cookie": f"__Host-ashley_session={TOKEN}"})
    assert session_named.status_code == 401
    assert kiosk.effects() == (0, 0, 0) and kiosk.conversations.asked == []
