"""The OAuthConnections service (`ashley.services`): what an OAuth connection stores beyond a pasted one's address and
secret, beside `Connections` (whose implementation also implements this). The sealed secret is the refresh token; the row
keeps the sealed access token, its expiry and the granted scopes, so a pod on either site reuses an access token another
obtained. Callers that add, reconnect or renew an OAuth connection use this; everything else stays on `Connections`."""

from abc import abstractmethod

from ..services import Service
from .connections import ConnectionsUnavailable
from .model import Connection, Grant, Holder, Kind, OAuthState


class OAuthConnections(Service):
    @classmethod
    def null(cls) -> "OAuthConnections":
        return NullOAuthConnections()

    @abstractmethod
    async def add_oauth(self, household_id: int, kind: Kind, label: str, base_url: str, grant: Grant,
                        added_by: int, holder: Holder | None = None) -> Connection:
        """`Connections.add` for an OAuth kind: the grant's refresh token is the secret, and its access token, expiry and
        scopes are stored with it. Raises as `Connections.add` does, and ValueError for a grant with no refresh token."""

    @abstractmethod
    async def replace_oauth(self, connection_id: int, household_id: int, person_id: int, base_url: str,
                            grant: Grant) -> Connection | None:
        """`Connections.replace` for an OAuth connection, which also clears its `needs` and raises its
        `secret_version`. None when it is not visible to `person_id`. Raises ValueError for a grant with no refresh
        token."""

    @abstractmethod
    async def state(self, connection_id: int, household_id: int, person_id: int | None = None) -> OAuthState | None:
        """A connection's tokens for renewal, when it is visible to `person_id`; None otherwise. Raises
        ConnectionsUnavailable."""

    @abstractmethod
    async def renewed(self, connection_id: int, version: int, grant: Grant) -> bool:
        """Store a refreshed `grant`'s access token and expiry (and its refresh token, when it carries one), only where
        the row's `secret_version` is still `version`, raising it. False, nothing written, when another pod got there
        first. Raises ConnectionsUnavailable."""

    @abstractmethod
    async def needs_reconnect(self, connection_id: int, version: int) -> bool:
        """Set `needs` to `reconnect` after the provider refused the refresh token, only where `secret_version` is still
        `version`, raising it. False, nothing written, when the row changed since. Raises ConnectionsUnavailable."""


class NullOAuthConnections(OAuthConnections):
    async def add_oauth(self, household_id: int, kind: Kind, label: str, base_url: str, grant: Grant,
                        added_by: int, holder: Holder | None = None) -> Connection:
        raise ConnectionsUnavailable("connections are not wired")

    async def replace_oauth(self, connection_id: int, household_id: int, person_id: int, base_url: str,
                            grant: Grant) -> Connection | None:
        raise ConnectionsUnavailable("connections are not wired")

    async def state(self, connection_id: int, household_id: int, person_id: int | None = None) -> OAuthState | None:
        raise ConnectionsUnavailable("connections are not wired")

    async def renewed(self, connection_id: int, version: int, grant: Grant) -> bool:
        raise ConnectionsUnavailable("connections are not wired")

    async def needs_reconnect(self, connection_id: int, version: int) -> bool:
        raise ConnectionsUnavailable("connections are not wired")
