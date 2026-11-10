"""Helpers for the web push tests: a VAPID key pair made fresh, a browser on a real push service's host, a recording
`Sender`, and an in-memory `Subscriptions` registered by the `subscriptions` fixture."""

import base64
from collections.abc import Generator
from dataclasses import dataclass, field

import pytest
from ashley import services
from ashley.channels.push.sender import Notification, Sender, Sent
from ashley.channels.push.subscriptions import Browser, Subscription, Subscriptions, SubscriptionsUnavailable
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

P256DH = base64.urlsafe_b64encode(b"\x04" + bytes(64)).decode().rstrip("=")
AUTH = base64.urlsafe_b64encode(bytes(16)).decode().rstrip("=")


def b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def key_pair() -> tuple[str, str]:
    """A fresh VAPID pair, (public, private raw), base64url as the settings carry them."""
    private = ec.generate_private_key(ec.SECP256R1())
    public = private.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return b64(public), b64(private.private_numbers().private_value.to_bytes(32, "big"))


def browser(n: int = 1) -> Browser:
    return Browser(f"https://fcm.googleapis.com/fcm/send/browser-{n}", P256DH, AUTH)


@dataclass
class FakeSender(Sender):
    """Records each send; answers `outcomes[endpoint]` when set, else `ok`."""

    outcomes: dict[str, Sent] = field(default_factory=dict[str, Sent])
    sends: list[tuple[Browser, Notification]] = field(default_factory=list[tuple[Browser, Notification]])

    async def send(self, browser: Browser, notification: Notification) -> Sent:
        self.sends.append((browser, notification))
        return self.outcomes.get(browser.endpoint, Sent("ok", 201))


@dataclass
class FakeSubscriptions(Subscriptions):
    """Subscriptions in a list; `down` makes every call raise."""

    rows: list[Subscription] = field(default_factory=list[Subscription])
    delivered_ids: list[int] = field(default_factory=list[int])
    down: bool = False

    def _check(self) -> None:
        if self.down:
            raise SubscriptionsUnavailable("down")

    async def add(self, household_id: int, person_id: int, browser: Browser) -> None:
        self._check()
        self.rows = [r for r in self.rows if r.browser.endpoint != browser.endpoint]
        self.rows.append(Subscription(len(self.rows) + 100, household_id, person_id, browser))

    async def remove(self, person_id: int, endpoint: str) -> None:
        self._check()
        self.rows = [r for r in self.rows if not (r.person_id == person_id and r.browser.endpoint == endpoint)]

    async def count(self, person_id: int, endpoint: str | None = None) -> tuple[int, bool]:
        self._check()
        mine = [r for r in self.rows if r.person_id == person_id]
        return len(mine), any(r.browser.endpoint == endpoint for r in mine)

    async def of(self, household_id: int, person_id: int) -> tuple[Subscription, ...]:
        self._check()
        return tuple(r for r in self.rows if r.household_id == household_id and r.person_id == person_id)

    async def delivered(self, subscription_id: int) -> None:
        self._check()
        self.delivered_ids.append(subscription_id)

    async def gone(self, subscription_id: int) -> None:
        self._check()
        self.rows = [r for r in self.rows if r.id != subscription_id]


@pytest.fixture
def subscriptions() -> Generator[FakeSubscriptions]:
    made = FakeSubscriptions()
    services.register(Subscriptions, made)
    yield made
    services.unregister(Subscriptions)
