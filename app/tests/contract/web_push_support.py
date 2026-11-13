"""Fakes for the blind web push tests, written from `api/models.py`, `openapi.json`, `decisions.md` ("Web push") and the
`Subscriptions` and `Sender` interfaces: an in-memory `Subscriptions`, a scripted `Sender`, VAPID identities, and the
`world` fixture that builds the real app over them. Nothing here touches a network or a database."""

import base64
import dataclasses
import os
from collections.abc import Generator
from dataclasses import dataclass, field
from typing import Any

import pytest
from ashley import services
from ashley.channels.outbox import Outbox
from ashley.channels.push.sender import Notification, Sender, Sent
from ashley.channels.push.subscriptions import Browser, Subscription, Subscriptions, SubscriptionsUnavailable
from ashley.main import create_app
from ashley.people.model import Person
from ashley.settings import Settings
from ashley.signin.sessions import Sessions
from contract_support import down_database, unreachable_conninfo
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient
from later_support import FakeOutbox
from web_chat_support import ALANA, COOKIE, ELLA, HOME as HOME, JSON, PUBLIC, TWELVE, FakeSessions

MARK = "zqPUSH9915"
FCM = "https://fcm.googleapis.com/fcm/send/"
MOZILLA = "https://updates.push.services.mozilla.com/wpush/v2/"


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def vapid_pair() -> tuple[str, str]:
    """A fresh VAPID key pair: (public, private), base64url."""
    made = ec.generate_private_key(ec.SECP256R1())
    public = made.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return _b64(public), _b64(made.private_numbers().private_value.to_bytes(32, "big"))


PUBLIC_KEY, PRIVATE_KEY = vapid_pair()
OTHER_PRIVATE = vapid_pair()[1]
SUBJECT = "mailto:ashley@ashley.test"


def settings(**changes: str) -> Settings:
    base = Settings(database_url=unreachable_conninfo(), build_version="t", public_url=PUBLIC,
                    vapid_public_key=PUBLIC_KEY, vapid_private_key=PRIVATE_KEY, vapid_subject=SUBJECT)
    return dataclasses.replace(base, **changes)


def keys() -> dict[str, str]:
    """A browser's `keys` as `PushSubscription.toJSON()` gives them: a 65-byte p256dh and a 16-byte auth."""
    return {"p256dh": _b64(bytes([4]) + os.urandom(64)), "auth": _b64(os.urandom(16))}


def endpoint(n: int, base: str = FCM) -> str:
    return f"{base}{MARK}-{n}"


def body(n: int = 1, base: str = FCM) -> dict[str, Any]:
    return {"endpoint": endpoint(n, base), "keys": keys()}


def browser(n: int = 1, base: str = FCM) -> Browser:
    k = keys()
    return Browser(endpoint(n, base), k["p256dh"], k["auth"])


class FakeSubscriptions(Subscriptions):
    """The contract of `Subscriptions` in memory: one browser belongs to one person, `of` is oldest first."""

    def __init__(self) -> None:
        self.rows: list[Subscription] = []
        self.next_id = 1
        self.down = False
        self.delivered_ids: list[int] = []
        self.gone_ids: list[int] = []

    def _check(self) -> None:
        if self.down:
            raise SubscriptionsUnavailable("down")

    async def add(self, household_id: int, person_id: int, browser: Browser) -> None:
        self._check()
        old = [r for r in self.rows if r.browser.endpoint == browser.endpoint]
        self.rows = [r for r in self.rows if r not in old]
        self.rows.append(Subscription(old[0].id if old else self._take_id(), household_id, person_id, browser))

    def _take_id(self) -> int:
        self.next_id += 1
        return self.next_id - 1

    async def remove(self, person_id: int, endpoint: str) -> None:
        self._check()
        self.rows = [r for r in self.rows if not (r.person_id == person_id and r.browser.endpoint == endpoint)]

    async def count(self, person_id: int, endpoint: str | None = None) -> tuple[int, bool]:
        self._check()
        mine = [r for r in self.rows if r.person_id == person_id]
        return len(mine), endpoint is not None and any(r.browser.endpoint == endpoint for r in mine)

    async def of(self, household_id: int, person_id: int) -> tuple[Subscription, ...]:
        self._check()
        return tuple(r for r in self.rows if r.person_id == person_id and r.household_id == household_id)

    async def delivered(self, subscription_id: int) -> None:
        self._check()
        self.delivered_ids.append(subscription_id)

    async def gone(self, subscription_id: int) -> None:
        self._check()
        self.gone_ids.append(subscription_id)
        self.rows = [r for r in self.rows if r.id != subscription_id]

    def endpoints(self, person_id: int) -> list[str]:
        return [r.browser.endpoint for r in self.rows if r.person_id == person_id]

    def seed(self, person: Person, *browsers: Browser) -> list[Subscription]:
        made: list[Subscription] = []
        for b in browsers:
            self.rows.append(Subscription(self._take_id(), person.household_id, person.id, b))
            made.append(self.rows[-1])
        return made


@dataclass
class FakeSender(Sender):
    """Records each push; answers `Sent("ok")` unless `answers` names that endpoint."""

    answers: dict[str, Sent] = field(default_factory=dict[str, Sent])
    pushed: list[tuple[Browser, Notification]] = field(default_factory=list[tuple[Browser, Notification]])

    async def send(self, browser: Browser, notification: Notification) -> Sent:
        self.pushed.append((browser, notification))
        return self.answers.get(browser.endpoint, Sent("ok"))

    def endpoints(self) -> list[str]:
        return [b.endpoint for b, _ in self.pushed]


@dataclass
class World:
    app: TestClient
    subs: FakeSubscriptions

    def call(self, method: str, path: str, person: Person | None = ALANA, payload: dict[str, Any] | None = None,
             headers: dict[str, str] | None = None) -> Any:
        cookie = {} if person is None else {"cookie": f"{COOKIE}=t-{person.id}"}
        return self.app.request(method, path, json=payload, headers={**JSON, **cookie, **(headers or {})})


def build(config: Settings, wired: bool = True) -> Generator[World]:
    """The app over fakes. Wiring registers `Subscriptions` only when push is set up, so a process without it keeps the
    Null Object: `wired=False` leaves it that way (`subs` then stays empty)."""
    app = create_app(config, down_database(config.database_url))
    subs = FakeSubscriptions()
    services.register(Sessions, FakeSessions(ALANA, ELLA, TWELVE))
    if wired:
        services.register(Subscriptions, subs)
    try:
        yield World(TestClient(app, base_url=PUBLIC), subs)
    finally:
        if wired:
            services.unregister(Subscriptions)


@pytest.fixture
def world() -> Generator[World]:
    yield from build(settings())


@pytest.fixture
def subs() -> Generator[FakeSubscriptions]:
    made = FakeSubscriptions()
    services.register(Subscriptions, made)
    yield made
    services.unregister(Subscriptions)


@pytest.fixture
def phone_outbox() -> Generator[FakeOutbox]:
    made = FakeOutbox()
    services.register(Outbox, made)
    yield made
    services.unregister(Outbox)

