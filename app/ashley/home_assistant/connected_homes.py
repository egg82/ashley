"""Homes from households' `home_assistant` connections: one client per household, kept while its address and token
are unchanged and closed once they change or the connection goes. Every `of` reads the connection, so a replacement on
either site is seen on the next call.

The env's HA (`HA_URL`, `HA_TOKEN`) answers for its one household while that household's connection is not settled:
with no key to open connections, or before any row of it has been seen, while the seed (`seed.seed_from_env`) is tried
again on a read, at most once per `RETRY_S`. So a seed that failed at start (the database away during a rollout, or a
pod ahead of the migration) heals without a restart. Once a row has been seen, a person removing it is respected."""

import logging
import time
from collections.abc import Callable
from dataclasses import replace

import httpx2
from pydantic import BaseModel, ValidationError

from .. import logs
from ..connections import answered, ports
from ..connections.connections import Connections, ConnectionsUnavailable
from ..connections.model import Opened
from .client import HomeAssistant, connect as connect_client
from .ha_house import HaHouse
from .homes import Home, HomeAssistantFailed, Homes, HomesUnavailable
from .house import House
from .house_settings import load as load_house_settings
from .rest_automations import AutomationsConfig, RestAutomations
from .seed import FALLBACK_HOUSEHOLD, seed_from_env

log = logging.getLogger("ashley.home_assistant")
_CHECK_TIMEOUT_S = 10
RETRY_S = 60.0
"""How often a read tries the env's seed again while the fallback household has no row."""


class _Running(BaseModel):
    message: str


def _record_answers(client: HomeAssistant, connection_id: int) -> HomeAssistant:
    """The client, recording against the connection: every response of a successful JSON read, and every
    WebSocket command that succeeds, moves its `checked_at`: one write by primary key per answered request or command,
    the same for each of her reads."""
    async def on_response(response: httpx2.Response) -> None:
        if response.is_success and response.headers.get("content-type", "").startswith("application/json"):
            await answered.record(connection_id)

    hooks = client.http.event_hooks
    client.http.event_hooks = {**hooks, "response": [*hooks["response"], on_response]}

    async def on_command() -> None:
        await answered.record(connection_id)

    return replace(client, answered=on_command)


class ConnectedHomes(Homes):
    def __init__(self, connections: Connections, config: AutomationsConfig,
                 connect: Callable[[str, str], HomeAssistant] = connect_client,
                 env: tuple[str, str] | None = None, fallback_household: int = FALLBACK_HOUSEHOLD,
                 clock: Callable[[], float] = time.monotonic,
                 house: Callable[[HomeAssistant], House] | None = None) -> None:
        """`connect` makes a client for a base URL and token; it must not follow redirects. `env` is the env's HA
        (base URL, token), answering for `fallback_household` alone while its connection is not settled. `house` makes the
        House over a client; by default Home Assistant's (`ha_house.HaHouse`)."""
        self._connections = connections
        self._config = config
        settings = load_house_settings()

        def over_home_assistant(client: HomeAssistant) -> House:
            return HaHouse(client, settings)
        self._house: Callable[[HomeAssistant], House] = house or over_home_assistant
        self._connect = connect
        self._env = env
        self._fallback = None if env is None else self._home(fallback_household, *env)
        self._clock = clock
        self._settled = env is None
        self._next_seed = float("-inf")
        self._known: dict[int, tuple[str, str, Home]] = {}

    def _home(self, household_id: int, base_url: str, token: str, connection_id: int | None = None) -> Home:
        client = self._connect(base_url, token)
        if connection_id is not None:
            client = _record_answers(client, connection_id)
        return Home(household_id, client, RestAutomations(client, self._config), self._house(client))

    def _falls_back(self, household_id: int) -> bool:
        return self._fallback is not None and household_id == self._fallback.household_id

    async def of(self, household_id: int) -> Home | None:
        if not self._connections.can_open():
            return self._fallback if self._falls_back(household_id) else None
        try:
            opened = await ports.opened(self._connections, "house", household_id)
        except ConnectionsUnavailable as e:
            return self._unreadable(household_id, e)
        if self._falls_back(household_id):
            if opened is None and not self._settled:
                opened = await self._seeded(household_id)
                if opened is None:
                    return self._fallback
            self._settled = self._settled or opened is not None
        return await self._current(household_id, opened)

    def _unreadable(self, household_id: int, error: ConnectionsUnavailable) -> Home:
        known = self._known.get(household_id)
        logs.warning(log, "homes.unreadable", household=household_id, kept=known is not None)
        if known is not None:
            return known[2]
        if self._falls_back(household_id) and not self._settled and self._fallback is not None:
            return self._fallback
        raise HomesUnavailable("the household's connections could not be read") from error

    async def _seeded(self, household_id: int) -> Opened | None:
        """The household's connection once the env's seed is decided, None while it is not or not due again."""
        if self._env is None or self._clock() < self._next_seed:
            return None
        self._next_seed = self._clock() + RETRY_S
        outcome = await seed_from_env(self._connections, *self._env, household_id=household_id)
        if outcome not in ("seeded", "kept"):
            return None
        try:
            return await ports.opened(self._connections, "house", household_id)
        except ConnectionsUnavailable:
            return None

    async def _current(self, household_id: int, opened: Opened | None) -> Home | None:
        known = self._known.get(household_id)
        if opened is None and known is None:
            return None
        if opened is not None and known is not None and known[:2] == (opened.connection.base_url, opened.secret):
            return known[2]
        home = None
        if opened is None:
            self._known.pop(household_id, None)
        else:
            home = self._home(household_id, opened.connection.base_url, opened.secret, opened.connection.id)
            self._known[household_id] = (opened.connection.base_url, opened.secret, home)
        logs.info(log, "homes.changed", household=household_id, reached=home is not None)
        if known is not None:
            await known[2].home_assistant.http.aclose()
        return home

    async def check(self, base_url: str, token: str) -> None:
        client = self._connect(base_url, token)
        try:
            response = await client.http.get("/api/", timeout=_CHECK_TIMEOUT_S)
        except httpx2.HTTPError as e:
            raise HomeAssistantFailed("unreachable") from e
        finally:
            await client.http.aclose()
        if response.status_code in (401, 403):
            raise HomeAssistantFailed("refused")
        if response.status_code == 404:
            raise HomeAssistantFailed("not_home_assistant")
        if not response.is_success:
            raise HomeAssistantFailed("unreachable")
        try:
            _Running.model_validate_json(response.content)
        except ValidationError as e:
            raise HomeAssistantFailed("not_home_assistant") from e

    async def close(self) -> None:
        """Close every client this made, and the fallback's."""
        homes = [k[2] for k in self._known.values()] + ([] if self._fallback is None else [self._fallback])
        self._known.clear()
        for home in homes:
            await home.home_assistant.http.aclose()
