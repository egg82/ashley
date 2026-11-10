"""Renewing an OAuth connection's access token (`decisions.md`, "A kind's secret can come from OAuth"). The access
token is kept sealed on the row with its expiry, so a pod on either site uses one another pod obtained. A pod that
finds it within `margin_s` of expiry refreshes and stores the result only where the row's `secret_version` is still the
one it read; a pod that loses reads the row again and uses the winner's token. A provider that refuses the refresh
token marks the connection `needs` `reconnect` and nothing is deleted."""

import logging
from abc import abstractmethod

from .. import logs, services
from ..services import Service
from .oauth_connections import OAuthConnections
from .kinds import Connect, ConnectionKinds, OAuth
from .model import OAuthState
from .oauth import OAuthProviders, OAuthRefused, OAuthUnavailable

log = logging.getLogger("ashley.connections")


class NeedsReconnect(Exception):
    """The connection's grant was refused, or it is already marked `needs` something; its person must connect again."""


class Renewal(Service):
    @classmethod
    def null(cls) -> "Renewal":
        return NullRenewal()

    @abstractmethod
    async def access_token(self, connection_id: int, household_id: int, person_id: int | None = None) -> str | None:
        """A usable access token for an OAuth connection visible to `person_id`, refreshed when it is within the margin
        of expiry; None when there is no such OAuth connection visible to them. Raises NeedsReconnect, OAuthUnavailable
        (the provider could not be reached or answered no token), ConnectionsUnavailable."""


class NullRenewal(Renewal):
    async def access_token(self, connection_id: int, household_id: int, person_id: int | None = None) -> str | None:
        raise OAuthUnavailable("renewal is not wired")


class OAuthRenewal(Renewal):
    def __init__(self, margin_s: int) -> None:
        self._margin_s = margin_s

    async def access_token(self, connection_id: int, household_id: int, person_id: int | None = None) -> str | None:
        state = await services.get(OAuthConnections).state(connection_id, household_id, person_id)
        if state is None or not isinstance(_connect(state), OAuth):
            return None
        if state.opened.connection.needs is not None:
            raise NeedsReconnect
        if state.access_token is not None and state.expires_in_s is not None and state.expires_in_s > self._margin_s:
            return state.access_token
        return await self._refreshed(state, household_id, person_id)

    async def _refreshed(self, state: OAuthState, household_id: int, person_id: int | None) -> str | None:
        connections, connection = services.get(OAuthConnections), state.opened.connection
        connect = _connect(state)
        provider = services.get(OAuthProviders).get(connect.provider) if isinstance(connect, OAuth) else None
        if provider is None:
            raise OAuthUnavailable("the provider is not configured")
        try:
            grant = await provider.refresh(state.opened.secret)
        except OAuthRefused:
            marked = await connections.needs_reconnect(connection.id, state.version)
            logs.warning(log, "connections.refresh_refused", connection=connection.id, kind=connection.kind,
                         reason="invalid_grant", lost_race=not marked)
            if marked:
                raise NeedsReconnect from None
            return await self._winner(connection.id, household_id, person_id)
        except OAuthUnavailable as e:
            logs.warning(log, "connections.refresh_failed", connection=connection.id, kind=connection.kind,
                         why=str(e))
            raise
        won = await connections.renewed(connection.id, state.version, grant)
        logs.info(log, "connections.refreshed", connection=connection.id, kind=connection.kind, lost_race=not won)
        return grant.access_token if won else await self._winner(connection.id, household_id, person_id)

    async def _winner(self, connection_id: int, household_id: int, person_id: int | None) -> str | None:
        """The token the pod that won the write stored."""
        state = await services.get(OAuthConnections).state(connection_id, household_id, person_id)
        if state is None:
            return None
        if state.opened.connection.needs is not None:
            raise NeedsReconnect
        if state.access_token is None:
            raise OAuthUnavailable("no access token is stored")
        return state.access_token


def _connect(state: OAuthState) -> Connect | None:
    kind = services.get(ConnectionKinds).get(state.opened.connection.kind)
    return None if kind is None else kind.connect
