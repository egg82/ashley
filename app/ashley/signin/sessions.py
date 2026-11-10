"""The Sessions service (`ashley.services`): sign-in's state, all of it in Postgres so any pod on either site can carry
any step. The sign-ins in flight, the sessions they open, the accounts refused because no person has them yet, and a
signed-in person's links of another account in flight.
Callers import only this module and `model`; the Postgres implementation lives beside it.

A session token and a sign-in's state are random, handed to the browser once and stored only as their SHA-256, so a
database read never yields one that works. Neither is ever logged, nor their hashes; session and person ids are."""

from abc import abstractmethod

from ..services import Service
from .model import LinkPending, Opened, Pending, SignedIn


class SessionsUnavailable(Exception):
    """The database could not be reached. Transient: the caller may retry."""


class Sessions(Service):
    @classmethod
    def null(cls) -> "Sessions":
        return NullSessions()

    @abstractmethod
    async def begin(self, state: str, pending: Pending) -> bool:
        """Store a sign-in in flight under `state`. False, storing nothing, when the most sign-ins allowed in flight at
        once already are (the policy's `max_pending`). Expired ones are swept first. Raises SessionsUnavailable."""

    @abstractmethod
    async def take(self, state: str) -> Pending | None:
        """The sign-in stored under `state`, removed so it can be taken once; None when there is none or it is past the
        policy's `pending_minutes`. Raises SessionsUnavailable."""

    @abstractmethod
    async def open(self, system: str, external_id: str) -> Opened | None:
        """Open a session for the person the account maps to (`accounts`, written by `python -m ashley.people`); None,
        opening nothing, when no person has that account: it is never guessed. Expired sessions are swept first.
        Raises SessionsUnavailable."""

    @abstractmethod
    async def find(self, token: str) -> SignedIn | None:
        """The live session `token` names, and records its use; None when it names none, or one past its expiry or
        idle for too long. Raises SessionsUnavailable."""

    @abstractmethod
    async def close(self, token: str) -> SignedIn | None:
        """End the session `token` names; the session ended, or None when it named none. Raises SessionsUnavailable."""

    @abstractmethod
    async def refused(self, system: str, external_id: str, username: str) -> None:
        """Record an account refused because no person has it, for the admin to map, and sweep the ones past the
        policy's `unmapped_retention_days`; `python -m ashley.signin unmapped` lists them. Raises
        SessionsUnavailable."""

    @abstractmethod
    async def begin_link(self, state: str, pending: LinkPending) -> bool:
        """Store a link in flight under `state`, apart from sign-ins, so neither flow's state completes the other. False,
        storing nothing, when `max_pending` links already are in flight. Expired ones are swept first. Raises
        SessionsUnavailable."""

    @abstractmethod
    async def take_link(self, state: str) -> LinkPending | None:
        """The link stored under `state`, removed so it can be taken once; None when there is none or it is past the
        policy's `pending_minutes`. Raises SessionsUnavailable."""


class NullSessions(Sessions):
    """Signs no one in: what an unwired process sees. Every call raises SessionsUnavailable, so a missing registration
    is a 503 rather than everyone signed out."""

    async def begin(self, state: str, pending: Pending) -> bool:
        raise SessionsUnavailable("Sessions is not wired")

    async def take(self, state: str) -> Pending | None:
        raise SessionsUnavailable("Sessions is not wired")

    async def open(self, system: str, external_id: str) -> Opened | None:
        raise SessionsUnavailable("Sessions is not wired")

    async def find(self, token: str) -> SignedIn | None:
        raise SessionsUnavailable("Sessions is not wired")

    async def close(self, token: str) -> SignedIn | None:
        raise SessionsUnavailable("Sessions is not wired")

    async def refused(self, system: str, external_id: str, username: str) -> None:
        raise SessionsUnavailable("Sessions is not wired")

    async def begin_link(self, state: str, pending: LinkPending) -> bool:
        raise SessionsUnavailable("Sessions is not wired")

    async def take_link(self, state: str) -> LinkPending | None:
        raise SessionsUnavailable("Sessions is not wired")
