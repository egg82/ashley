"""Households' Home Assistants for tests: a stand-in HA behind `httpx2.MockTransport` that records each request with
the token it carried, a `connect` for `ConnectedHomes` that reaches it, and `AnyHousehold`, a Homes that answers one
Home for every household, for tests about what is built on a house rather than whose house it is, and `ByHousehold`,
one Home per household given, which can go down."""

from dataclasses import dataclass, field

import httpx2
from ashley.home_assistant.automations import Automations, NullAutomations
from ashley.home_assistant.client import HomeAssistant
from ashley.home_assistant.homes import Home, Homes, HomesUnavailable
from ashley.home_assistant.house import NullHouse

TOKEN = "the-households-ha-token"


@dataclass
class StandIn:
    """Answers `GET /api/` as HA does (`{"message": "API running."}`) to `token`, 401 to any other; `status` or `raw`
    replace the answer; `down` fails every request to connect. `seen` is (base URL, path, token) per request."""

    token: str = TOKEN
    status: int | None = None
    raw: bytes | None = None
    down: bool = False
    seen: list[tuple[str, str, str]] = field(default_factory=list[tuple[str, str, str]])
    made: list[httpx2.AsyncClient] = field(default_factory=list[httpx2.AsyncClient])
    """Every client `connect` made, in order."""

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        if self.down:
            raise httpx2.ConnectError("down", request=request)
        given = request.headers.get("authorization", "").removeprefix("Bearer ")
        base = f"{request.url.scheme}://{request.url.netloc.decode()}"
        self.seen.append((base, request.url.path, given))
        if self.status is not None or self.raw is not None:
            return httpx2.Response(self.status or 200, content=self.raw or b"{}")
        if given != self.token:
            return httpx2.Response(401, content=b"401: Unauthorized")
        if request.url.path == "/api/":
            return httpx2.Response(200, json={"message": "API running."})
        return httpx2.Response(200, json={"state": "home"})

    def connect(self, base_url: str, token: str) -> HomeAssistant:
        """What `ashley.home_assistant.client.connect` makes, reaching this stand-in."""
        http = httpx2.AsyncClient(base_url=base_url, headers={"Authorization": f"Bearer {token}"},
                                  transport=httpx2.MockTransport(self.handle))
        self.made.append(http)
        return HomeAssistant(http)


class AnyHousehold(Homes):
    """Every household reaches the same Home, built over `automations`."""

    def __init__(self, automations: Automations, home_assistant: HomeAssistant | None = None) -> None:
        self._automations = automations
        self._home_assistant = home_assistant or HomeAssistant(httpx2.AsyncClient(base_url="http://ha.test:8123"))

    async def of(self, household_id: int) -> Home | None:
        return Home(household_id, self._home_assistant, self._automations, NullHouse())

    async def check(self, base_url: str, token: str) -> None:
        raise NotImplementedError


class ByHousehold(Homes):
    def __init__(self) -> None:
        self.homes: dict[int, Home] = {}
        self.down = False
        self.asked: list[int] = []

    def give(self, household_id: int, base: str, stand: StandIn | None = None) -> Home:
        home = Home(household_id, (stand or StandIn()).connect(base, "t"), NullAutomations(), NullHouse())
        self.homes[household_id] = home
        return home

    async def of(self, household_id: int) -> Home | None:
        self.asked.append(household_id)
        if self.down:
            raise HomesUnavailable("down")
        return self.homes.get(household_id)

    async def check(self, base_url: str, token: str) -> None:
        raise NotImplementedError
