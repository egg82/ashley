"""The ConnectPending service (`ashley.services`): OAuth connects in flight, between sending the browser to the
provider and its callback. A state is random, handed to the browser once and stored only as its SHA-256; the PKCE
verifier is sealed under the connections key; each row is bound to the person who started it and holds the kind,
label and holder they chose, so the callback needs nothing from its query but the code and state. Its own table, so
a state from a sign-in or a Discord link cannot complete a connect."""

from abc import abstractmethod
from dataclasses import dataclass, field

from ..services import Service
from .connections import ConnectionsUnavailable
from .model import Holder


@dataclass(frozen=True)
class Pending:
    """A connect in flight: who started it, what they chose, and the PKCE verifier (left out of `repr`)."""

    household_id: int
    person_id: int
    kind: str
    label: str
    holder: Holder
    verifier: str = field(repr=False)


class ConnectPending(Service):
    @classmethod
    def null(cls) -> "ConnectPending":
        return NullConnectPending()

    @abstractmethod
    async def begin(self, state: str, pending: Pending) -> bool:
        """Store a connect in flight under `state`. False, storing nothing, when the most allowed in flight at once
        already are. Expired ones are swept first. Raises ConnectionsUnavailable."""

    @abstractmethod
    async def take(self, state: str) -> Pending | None:
        """The connect stored under `state`, removed so it can be taken once; None when there is none or it is past
        its lifetime. Raises ConnectionsUnavailable."""


class NullConnectPending(ConnectPending):
    async def begin(self, state: str, pending: Pending) -> bool:
        raise ConnectionsUnavailable("connections are not wired")

    async def take(self, state: str) -> Pending | None:
        raise ConnectionsUnavailable("connections are not wired")
