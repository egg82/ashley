"""A fake Home Assistant per base URL behind `httpx2.MockTransport`, recording every request with its host, path and
bearer token, and an in-memory Connections. `FakeHouses.connect` is the `connect` a `ConnectedHomes` is built with and
`FakeHouses.house` its `house`: a House whose every read and act goes to its client's host."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx2
from ashley.connections.connections import Connections, ConnectionsUnavailable
from ashley.connections.model import Connection, Holder, Kind, Opened
from ashley.home_assistant.client import HomeAssistant
from ashley.home_assistant.house import House, HouseUnavailable, Performed, State
from ashley.home_assistant.rest_automations import AutomationsConfig
from house_double_support import MemoryHouse, state

EPOCH = datetime(2026, 10, 31, tzinfo=UTC)
CONFIG = AutomationsConfig(timeout_s=2.0, entity_tries=1, entity_wait_s=0.0)
ENV = ("http://env-ha.test:8123", "env-token")
A_URL, A_TOKEN = "http://a-house.test:8123", "token-of-a"
B_URL, B_TOKEN = "http://b-house.test:8123", "token-of-b"


@dataclass
class FakeHouses:
    """Every house answers `GET /api/` with HA's greeting for the token it was made with; `refuse` hosts answer 401;
    `down` hosts raise a connect error. `seen` is (host, method, path, bearer)."""

    seen: list[tuple[str, str, str, str]] = field(default_factory=list[tuple[str, str, str, str]])
    refuse: set[str] = field(default_factory=set[str])
    down: set[str] = field(default_factory=set[str])
    made: list[tuple[str, str]] = field(default_factory=list[tuple[str, str]])
    states: dict[str, str] = field(default_factory=dict[str, str])
    lights: tuple[str, ...] = ()
    greeting: dict[str, object] = field(default_factory=lambda: {"message": "API running."})

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        host = request.url.host
        self.seen.append((f"{host}:{request.url.port}" if request.url.port else host, request.method,
                          request.url.path, request.headers.get("authorization", "")))
        if host in self.down:
            raise httpx2.ConnectError("down")
        if host in self.refuse:
            return httpx2.Response(401, json={"message": "401: Unauthorized"})
        if request.url.path in ("/api/", "/api"):
            return httpx2.Response(200, json=self.greeting)
        state = self.states.get(host, "home")
        if request.url.path == "/api/states":
            return httpx2.Response(200, json=[{"entity_id": "person.pat", "state": state, "attributes": {}}])
        if request.url.path.startswith("/api/states/"):
            return httpx2.Response(200, json={"entity_id": request.url.path.rsplit("/", 1)[1], "state": state,
                                              "attributes": {}})
        if request.url.path == "/api/config":
            return httpx2.Response(200, json={"latitude": 1.0, "longitude": 2.0, "time_zone": "UTC"})
        return httpx2.Response(200, json={})

    def connect(self, base_url: str, token: str) -> HomeAssistant:
        self.made.append((base_url, token))
        return HomeAssistant(httpx2.AsyncClient(transport=httpx2.MockTransport(self.handle), base_url=base_url,
                                                headers={"Authorization": f"Bearer {token}"}))

    def house(self, client: HomeAssistant) -> House:
        return HostHouse(client, self.lights)

    def hosts(self) -> set[str]:
        return {host for host, _, _, _ in self.seen}

    def tokens(self) -> set[str]:
        return {bearer for _, _, _, bearer in self.seen}


@dataclass
class HeldConnections(Connections):
    """Connections in memory. `down` makes every call raise ConnectionsUnavailable; `reads` counts read calls."""

    held: dict[tuple[int, str], Opened] = field(default_factory=dict[tuple[int, str], Opened])
    down: bool = False
    reads: int = 0
    seed_fails: bool = False
    seeds: list[tuple[int, str]] = field(default_factory=list[tuple[int, str]])

    def can_open(self) -> bool:
        return True

    def connect(self, household_id: int, base: str, secret: str, kind: Kind = "home_assistant") -> None:
        connection = Connection(len(self.held) + 1, household_id, kind, base, 1, EPOCH, EPOCH)
        self.held[(household_id, kind)] = Opened(connection, secret)

    def _up(self) -> None:
        if self.down:
            raise ConnectionsUnavailable("down")

    async def of_household(self, household_id: int, person_id: int | None = None) -> tuple[Connection, ...]:
        self._up()
        return tuple(o.connection for (h, _), o in self.held.items() if h == household_id)

    async def opened(self, connection_id: int, household_id: int, person_id: int | None = None) -> Opened | None:
        self.reads += 1
        self._up()
        return next((o for (h, _), o in self.held.items() if o.connection.id == connection_id and h == household_id),
                    None)

    async def add(self, household_id: int, kind: Kind, label: str, base_url: str, secret: str,
                  added_by: int, holder: Holder | None = None) -> Connection:
        self._up()
        self.connect(household_id, base_url, secret, kind)
        return self.held[(household_id, kind)].connection

    async def replace(self, connection_id: int, household_id: int, person_id: int, base_url: str,
                      secret: str) -> Connection | None:
        raise NotImplementedError

    async def relabel(self, connection_id: int, household_id: int, person_id: int,
                      label: str) -> Connection | None:
        raise NotImplementedError

    async def seed(self, household_id: int, kind: Kind, base_url: str, secret: str) -> Connection | None:
        self.seeds.append((household_id, kind))
        self._up()
        if self.seed_fails:
            raise ConnectionsUnavailable("refused")
        if (household_id, kind) in self.held:
            return None
        self.connect(household_id, base_url, secret, kind)
        return self.held[(household_id, kind)].connection

    async def remove(self, connection_id: int, household_id: int, person_id: int | None) -> bool:
        self._up()
        slot = next((k for k, o in self.held.items() if o.connection.id == connection_id and k[0] == household_id),
                    None)
        return slot is not None and self.held.pop(slot, None) is not None

    async def answered(self, connection_id: int) -> None:
        self._up()


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class HostHouse(MemoryHouse):
    """Its one marker thing is named for the host its client reaches (`only_a_house_test`), beside a light for each of
    `lights`; every read and act first asks that host, so the fake sees which house and token reached it."""

    def __init__(self, client: HomeAssistant, lights: tuple[str, ...]) -> None:
        host = str(client.http.base_url.host).replace(".", "_").replace("-", "_")
        super().__init__(things=[state(f"light.only_{host}", f"only_{host}", "off", "Hall"),
                                 *(state(f"light.l{i}", name, "on", "Hall") for i, name in enumerate(lights))])
        self._client = client

    async def _asked(self, path: str) -> None:
        try:
            await (self._client.http.get(path) if path == "/api/states" else self._client.http.post(path))
        except httpx2.HTTPError as e:
            raise HouseUnavailable("down") from e

    async def states(self) -> tuple[State, ...]:
        await self._asked("/api/states")
        return await super().states()

    async def perform(self, action: str, ids: tuple[str, ...], data: Mapping[str, Any]) -> Performed:
        await self._asked("/api/services/" + action.replace(".", "/"))
        return await super().perform(action, ids, data)
