"""`keeper_grpc.GrpcBridge`'s side of Bridge's wire, with the stub and the generated messages faked: what each login
call sends and how a login error is read. Bridge's own decoding (`base64Decode` in 3.27.1's service_methods.go) is the
contract the encoding test holds the keeper to."""

import base64
import queue
from types import SimpleNamespace
from typing import Any

import pytest
from keeper_grpc import GrpcBridge
from keeper_link import LoginEvent, Reason


def _request(**fields: object) -> dict[str, object]:
    return fields


class _Stub:
    def __init__(self, events: "queue.Queue[LoginEvent]") -> None:
        self.sent: list[tuple[str, Any]] = []
        self._events = events

    def __getattr__(self, name: str) -> Any:
        def call(request: Any, metadata: Any, timeout: float) -> None:
            self.sent.append((name, request))
            self._events.put(LoginEvent("tfa"))
        return call


def _bridge() -> tuple[GrpcBridge, _Stub]:
    bridge = object.__new__(GrpcBridge)
    events: queue.Queue[LoginEvent] = queue.Queue()
    stub = _Stub(events)
    bridge.__dict__.update(_pb=SimpleNamespace(LoginRequest=_request), _stub=stub, _meta=(),
                           _login_events=events)
    return bridge, stub


@pytest.mark.parametrize("call,rpc", [("login", "Login"), ("second_factor", "Login2FA"),
                                      ("mailbox_password", "Login2Passwords")])
def test_each_login_call_sends_its_secret_base64_encoded(call: str, rpc: str) -> None:
    bridge, stub = _bridge()
    secret = "pässword with spaces & $ymbols!"
    getattr(bridge, call)("someone@proton.me", secret)
    name, request = stub.sent[-1]
    assert name == rpc
    assert request["username"] == "someone@proton.me"
    assert base64.b64decode(request["password"], validate=True).decode() == secret


def _event(which: str | None, **fields: Any) -> Any:
    def which_one_of(_: str) -> str | None:
        return which
    return SimpleNamespace(WhichOneof=which_one_of, **fields)


def _error(kind: int) -> Any:
    return _event("error", error=SimpleNamespace(type=kind))


def _answer(login: Any) -> LoginEvent:
    bridge, _ = _bridge()
    getattr(bridge, "_login_event")(login)
    return getattr(bridge, "_login_events").get_nowait()


@pytest.mark.parametrize("kind,reason", [
    (0, "credentials"), (1, "paid_plan"), (2, "connection"), (3, "code"), (4, "aborted"), (5, "mailbox_password"),
    (6, "aborted"), (7, "verification"), (8, "security_key"), (9, "security_key"), (10, "security_key"),
    (99, "other")])
def test_each_login_error_type_has_its_own_reason_and_a_log_line(
        kind: int, reason: Reason, capsys: pytest.CaptureFixture[str]) -> None:
    assert _answer(_error(kind)) == LoginEvent("error", reason=reason)
    assert f"event=proton_bridge.login_refused error_type={kind}" in capsys.readouterr().out


def _user(which: str) -> Any:
    return _event(which, **{which: SimpleNamespace(userID="u1")})


@pytest.mark.parametrize("login,expected,logged", [
    (_event("tfaRequested"), LoginEvent("tfa"), "tfaRequested"),
    (_event("tfaOrFidoRequested"), LoginEvent("tfa"), "tfaOrFidoRequested"),
    (_event("twoPasswordRequested"), LoginEvent("two_passwords"), "twoPasswordRequested"),
    (_user("finished"), LoginEvent("finished", user_id="u1"), "finished"),
    (_user("alreadyLoggedIn"), LoginEvent("finished", user_id="u1"), "alreadyLoggedIn"),
    (_event("fidoRequested"), LoginEvent("error", reason="security_key"), "fidoRequested"),
    (_event("loginFidoTouchRequested"), LoginEvent("error", reason="security_key"), "loginFidoTouchRequested"),
    (_event("loginFidoTouchCompleted"), LoginEvent("error", reason="security_key"), "loginFidoTouchCompleted"),
    (_event("loginFidoPinRequired"), LoginEvent("error", reason="security_key"), "loginFidoPinRequired"),
    (_event("somethingNew"), LoginEvent("error", reason="other"), "login_event_unhandled which=somethingNew")])
def test_each_login_event_is_answered_by_name_and_logged(
        login: Any, expected: LoginEvent, logged: str, capsys: pytest.CaptureFixture[str]) -> None:
    assert _answer(login) == expected
    assert logged in capsys.readouterr().out


def test_human_verification_carries_the_url_and_the_log_does_not(capsys: pytest.CaptureFixture[str]) -> None:
    url = "https://verify.proton.me/?methods=captcha&token=SECRET"
    got = _answer(_event("hvRequested", hvRequested=SimpleNamespace(hvUrl=url)))
    assert got == LoginEvent("human_verification", url=url)
    out = capsys.readouterr().out
    assert "event=proton_bridge.login_hv" in out and "SECRET" not in out


def test_a_verified_login_asks_bridge_to_use_the_details_it_kept() -> None:
    bridge, stub = _bridge()
    bridge.login("someone@proton.me", "pw", verified=True)
    assert stub.sent[-1][1]["useHvDetails"] is True
    bridge.login("someone@proton.me", "pw")
    assert "useHvDetails" not in stub.sent[-1][1]
