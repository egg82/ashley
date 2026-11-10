"""Sending one notification to one browser: the port the push singleton uses, and its one implementation over
pywebpush, the only module importing the Web Push libraries. The payload is encrypted to the browser's keys, so its push
service carries it without reading it."""

import asyncio
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal

import requests
from py_vapid import Vapid01
from pywebpush import WebPushException, webpush

from .config import Vapid
from .subscriptions import Browser


@dataclass(frozen=True)
class Notification:
    """What the browser shows: `title`, `body`, and the path on this site a click opens. `agree` is the held proposal the
    body shows, which the notification offers an Agree action for; None when it shows none."""

    title: str
    body: str
    url: str
    agree: int | None = None


@dataclass(frozen=True)
class Sent:
    """`ok`: the push service accepted it; `gone`: it answered 404 or 410, so the subscription no longer exists;
    `failed`: anything else, with the status when there was one."""

    outcome: Literal["ok", "gone", "failed"]
    status: int | None = None


class Sender(ABC):
    @abstractmethod
    async def send(self, browser: Browser, notification: Notification) -> Sent:
        """Push `notification` to `browser`. Never raises for what a push service or the network does."""


class WebPushSender(Sender):
    """pywebpush, run off the event loop since it blocks. A push service answers for itself, so a redirect is never
    followed: an endpoint cannot hand the request on to another address."""

    def __init__(self, vapid: Vapid, ttl_s: int, timeout_s: float) -> None:
        self._key = Vapid01.from_string(vapid.private_key)
        self._claims: dict[str, str | int] = {"sub": vapid.subject}
        self._ttl_s = ttl_s
        self._timeout_s = timeout_s

    async def send(self, browser: Browser, notification: Notification) -> Sent:
        return await asyncio.to_thread(self._send, browser, notification)

    def _send(self, browser: Browser, notification: Notification) -> Sent:
        data = json.dumps({"title": notification.title, "body": notification.body, "url": notification.url,
                           "agree": notification.agree})
        try:
            with requests.Session() as session:
                session.max_redirects = 0
                webpush({"endpoint": browser.endpoint, "keys": {"p256dh": browser.p256dh, "auth": browser.auth}},
                        data=data, vapid_private_key=self._key, vapid_claims=dict(self._claims), ttl=self._ttl_s,
                        timeout=self._timeout_s, requests_session=session)
        except WebPushException as e:
            status = e.response.status_code if e.response is not None else None
            return Sent("gone", status) if status in (404, 410) else Sent("failed", status)
        except (requests.RequestException, ValueError):
            return Sent("failed")
        return Sent("ok", 201)
