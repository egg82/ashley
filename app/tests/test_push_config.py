"""Web push's configuration and edges: her VAPID identity is usable only as one P-256 pair with a subject; an endpoint is
accepted only on a browser's own push service; the sender maps a push service's answer to `ok`, `gone` (404, 410) or
`failed`."""

import pytest
import requests
from ashley.channels.push import config as push_config, sender as sender_module
from ashley.channels.push.sender import Notification, Sent, WebPushSender
from ashley.settings import Settings
from contract.conversations_support import run
from push_support import browser, key_pair
from pywebpush import WebPushException

CONFIG = push_config.load()


def settings(public: str = "", private: str = "", subject: str = "mailto:admin@example.test") -> Settings:
    return Settings(database_url="postgresql://x", build_version="t", vapid_public_key=public,
                    vapid_private_key=private, vapid_subject=subject)


def test_one_pair_with_a_subject_is_her_identity() -> None:
    public, private = key_pair()
    found = push_config.vapid(settings(public, private))
    assert found is not None and (found.public_key, found.private_key) == (public, private)


@pytest.mark.parametrize("broken", ["missing_subject", "missing_public", "other_pair", "not_base64", "unset"])
def test_anything_else_is_push_off(broken: str) -> None:
    public, private = key_pair()
    other, _ = key_pair()
    given = {"missing_subject": settings(public, private, subject=""), "missing_public": settings("", private),
             "other_pair": settings(other, private), "not_base64": settings(public, "!!not a key!!"),
             "unset": settings(subject="")}[broken]
    assert push_config.vapid(given) is None


@pytest.mark.parametrize(("endpoint", "ok"), [
    ("https://fcm.googleapis.com/fcm/send/abc", True),
    ("https://updates.push.services.mozilla.com/wpush/v2/abc", True),
    ("https://web.push.apple.com/abc", True),
    ("https://wns2-par02p.notify.windows.com/w/?token=abc", True),
    ("http://fcm.googleapis.com/fcm/send/abc", False),
    ("https://fcm.googleapis.com:8443/fcm/send/abc", False),
    ("https://user@fcm.googleapis.com/fcm/send/abc", False),
    ("https://evil.example/fcm.googleapis.com", False),
    ("https://push.apple.com.evil.example/abc", False),
    ("https://10.0.0.1/abc", False),
    ("not a url", False),
])
def test_only_a_browsers_own_push_service_is_accepted(endpoint: str, ok: bool) -> None:
    assert push_config.is_push_service(endpoint, CONFIG) is ok


class _Answer:
    def __init__(self, status: int) -> None:
        self.status_code = status


@pytest.mark.parametrize(("raised", "sent"), [
    (None, Sent("ok", 201)),
    (WebPushException("gone", response=_Answer(410)), Sent("gone", 410)),
    (WebPushException("gone", response=_Answer(404)), Sent("gone", 404)),
    (WebPushException("busy", response=_Answer(429)), Sent("failed", 429)),
    (WebPushException("no answer"), Sent("failed", None)),
    (requests.ConnectionError("down"), Sent("failed", None)),
])
def test_the_sender_maps_what_the_push_service_answered(monkeypatch: pytest.MonkeyPatch,
                                                        raised: Exception | None, sent: Sent) -> None:
    calls: list[dict[str, object]] = []

    def fake_webpush(info: dict[str, object], **kwargs: object) -> None:
        calls.append({"info": info, **kwargs})
        if raised is not None:
            raise raised

    monkeypatch.setattr(sender_module, "webpush", fake_webpush)
    public, private = key_pair()
    identity = push_config.vapid(settings(public, private))
    assert identity is not None
    got: list[Sent] = []

    async def scenario() -> None:
        got.append(await WebPushSender(identity, 600, 2).send(browser(1), Notification("Ashley", "hi", "/")))

    run(scenario())
    assert got == [sent]
    (call,) = calls
    assert call["info"] == {"endpoint": browser(1).endpoint, "keys": {"p256dh": browser(1).p256dh,
                                                                       "auth": browser(1).auth}}
    assert call["data"] == '{"title": "Ashley", "body": "hi", "url": "/", "agree": null}' and call["ttl"] == 600
    session = call["requests_session"]
    assert isinstance(session, requests.Session) and session.max_redirects == 0
