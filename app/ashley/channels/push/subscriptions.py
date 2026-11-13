"""The Subscriptions service (`ashley.services`): which browsers each person has asked to be pushed to. Callers import
only this module; the Postgres implementation lives beside it. Wired once the deployment's secrets are settled and push is
(`config.identity`); otherwise the
Null Object raises, so the routes answer 503 and the turn loop offers no phone.

An endpoint is a secret URL that lets anyone push to that browser, and the keys are its encryption keys: none of them
is ever logged."""

from abc import abstractmethod
from dataclasses import dataclass

from ...services import Service


class SubscriptionsUnavailable(Exception):
    """Subscriptions could not be reached, or push is not wired. Transient."""


@dataclass(frozen=True)
class Browser:
    """What a browser hands over when it subscribes: its push service `endpoint`, and its `p256dh` and `auth` keys
    (base64url), which encrypt what is sent to it."""

    endpoint: str
    p256dh: str
    auth: str


@dataclass(frozen=True)
class Subscription:
    id: int
    household_id: int
    person_id: int
    browser: Browser


class Subscriptions(Service):
    @classmethod
    def null(cls) -> "Subscriptions":
        return NullSubscriptions()

    @abstractmethod
    async def add(self, household_id: int, person_id: int, browser: Browser) -> None:
        """Push to `browser` for that person from now on. One browser belongs to one person: subscribing an endpoint
        another person has moves it to this one, with the new keys. Raises SubscriptionsUnavailable."""

    @abstractmethod
    async def remove(self, person_id: int, endpoint: str) -> None:
        """Stop pushing to the browser at `endpoint`, when it is that person's; nothing otherwise. Raises
        SubscriptionsUnavailable."""

    @abstractmethod
    async def count(self, person_id: int, endpoint: str | None = None) -> tuple[int, bool]:
        """How many browsers that person has, and whether `endpoint` is one of them (False when None). Raises
        SubscriptionsUnavailable."""

    @abstractmethod
    async def of(self, household_id: int, person_id: int) -> tuple[Subscription, ...]:
        """Every browser of that person in that household, oldest first. Raises SubscriptionsUnavailable."""

    @abstractmethod
    async def delivered(self, subscription_id: int) -> None:
        """Record that a push to it was accepted just now. Raises SubscriptionsUnavailable."""

    @abstractmethod
    async def gone(self, subscription_id: int) -> None:
        """Forget it: its push service said it no longer exists. Raises SubscriptionsUnavailable."""


class NullSubscriptions(Subscriptions):
    """What a process without push sees: every call raises SubscriptionsUnavailable."""

    async def add(self, household_id: int, person_id: int, browser: Browser) -> None:
        raise SubscriptionsUnavailable("push is not wired")

    async def remove(self, person_id: int, endpoint: str) -> None:
        raise SubscriptionsUnavailable("push is not wired")

    async def count(self, person_id: int, endpoint: str | None = None) -> tuple[int, bool]:
        raise SubscriptionsUnavailable("push is not wired")

    async def of(self, household_id: int, person_id: int) -> tuple[Subscription, ...]:
        raise SubscriptionsUnavailable("push is not wired")

    async def delivered(self, subscription_id: int) -> None:
        raise SubscriptionsUnavailable("push is not wired")

    async def gone(self, subscription_id: int) -> None:
        raise SubscriptionsUnavailable("push is not wired")
