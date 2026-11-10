"""The whole app on a real database for the blind screen suite: two households with signed-in people, a Home Assistant
connection whose house is held in memory (so the catalogue and a button press are real), tablets that sign in by token,
and a recording Live. `on_app_loop` runs her tools where the app's database pool lives."""

import base64
import hashlib
import os
import secrets
from collections.abc import Callable, Coroutine, Generator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

import httpx2
import psycopg
from ashley import services
from ashley.api.person import SESSION_COOKIE
from ashley.home_assistant.automations import NullAutomations
from ashley.home_assistant.client import HomeAssistant
from ashley.home_assistant.homes import Home, Homes
from ashley.home_assistant.house import ActionInfo
from ashley.live.live import Live
from ashley.main import create_app
from ashley.people import admin
from ashley.settings import Settings
from contract.conversations_support import scalar
from fastapi.testclient import TestClient
from house_double_support import MemoryHouse, state
from httpx2 import Response
from live_support import FakeLive

PUBLIC = "https://ashley.test"
ORIGIN = {"origin": PUBLIC}
KEY = base64.b64encode(os.urandom(32)).decode()
HA_URL, HA_TOKEN = "http://ha.test:8123", "long-lived-token-for-the-test-house"
KIOSK = "__Host-ashley_kiosk"


@dataclass(frozen=True)
class People:
    alana: int
    sam: int
    kim: int
    home: int
    other: int
    tokens: dict[str, str]


def session(conn: psycopg.Connection, person: int, household: int, sub: str) -> str:
    account = admin.add_account(conn, person, "oidc", sub)
    token = secrets.token_urlsafe(16)
    conn.execute("INSERT INTO sessions (token_sha256, account_id, household_id, expires_at) "
                 "VALUES (%s, %s, %s, now() + interval '1 day')",
                 (hashlib.sha256(token.encode()).digest(), account, household))
    return token


def people_in(url: str) -> People:
    with psycopg.connect(url) as conn:
        home, other = admin.add_household(conn, "home", "America/Denver"), admin.add_household(conn, "other", "UTC")
        alana, sam, kim = (admin.add_person(conn, home, "Alana"), admin.add_person(conn, home, "Sam"),
                          admin.add_person(conn, other, "Kim"))
        return People(alana, sam, kim, home, other, {"alana": session(conn, alana, home, "a"),
                                                    "sam": session(conn, sam, home, "s"),
                                                    "kim": session(conn, kim, other, "k")})


def lit_house() -> MemoryHouse:
    house = MemoryHouse(things=[state("light.zq_hall", "Hall", "off"), state("light.zq_porch", "Porch", "on"),
                                state("lock.zq_front", "Front", "locked"), state("scene.zq_night", "Night", "unknown")])
    house.catalogue = [ActionInfo(a, a, {}, "none") for a in ("light.turn_on", "light.turn_off", "scene.turn_on")]
    return house


class FixedHomes(Homes):
    """Each household in `houses` has the one house given for it; `check` accepts any address."""

    def __init__(self, houses: dict[int, MemoryHouse]) -> None:
        self.houses = houses

    async def of(self, household_id: int) -> Home | None:
        house = self.houses.get(household_id)
        if house is None:
            return None
        client = HomeAssistant(httpx2.AsyncClient(transport=httpx2.MockTransport(lambda r: httpx2.Response(200, json={})),
                                                  base_url=HA_URL))
        return Home(household_id, client, NullAutomations(), house)

    async def check(self, base_url: str, token: str) -> None:
        return None


@dataclass
class Rig:
    client: TestClient
    people: People
    url: str
    live: FakeLive
    house: MemoryHouse

    def as_(self, who: str | None) -> None:
        self.client.cookies.clear()
        if who is not None:
            self.client.cookies.set(SESSION_COOKIE, self.people.tokens[who], domain="ashley.test")

    def tablet(self, household: int | None = None, token: str | None = None) -> tuple[int, str]:
        """A device of form `other` that signs in by the token returned."""
        secret = token or secrets.token_urlsafe(12)
        made = int(scalar(self.url, "INSERT INTO devices (household_id, name, place, audience, medium, kind, token_sha256) "
                          "VALUES (%s, 'tablet', 'hallway', 'present', 'text', 'chat', %s) RETURNING id",
                          (household or self.people.home, hashlib.sha256(secret.encode()).digest())))
        return made, secret

    def kiosk(self, path: str, token: str | None, method: str = "GET") -> Response:
        cookies = {} if token is None else {"cookie": f"{KIOSK}={token}"}
        if method == "GET":
            return self.client.get(path, headers=cookies)
        return self.client.post(path, json={}, headers={**ORIGIN, **cookies})

    def put_controls(self, device: int, base_version: int | None, *wanted: dict[str, str | None]) -> Response:
        body: dict[str, Any] = {"wanted": list(wanted)}
        if base_version is not None:
            body["base_version"] = base_version
        return self.client.put(f"/api/devices/{device}/controls", json=body, headers=ORIGIN)

    def controls(self, device: int) -> dict[str, Any]:
        got = self.client.get(f"/api/devices/{device}/controls")
        assert got.status_code == 200, got.text
        body: dict[str, Any] = got.json()
        return body

    def on_loop[T](self, work: Callable[[], Coroutine[Any, Any, T]]) -> T:
        assert self.client.portal is not None
        return self.client.portal.call(work)


@contextmanager
def rig(url: str) -> Generator[Rig]:
    people = people_in(url)
    house = lit_house()
    app = create_app(Settings(database_url=url, build_version="t", public_url=PUBLIC, connections_key=KEY))
    with TestClient(app, base_url=PUBLIC, follow_redirects=False) as client:
        live = FakeLive()
        services.register(Homes, FixedHomes({people.home: house, people.other: lit_house()}))
        services.register(Live, live)
        made = Rig(client, people, url, live, house)
        made.as_("alana")
        got = client.post("/api/connections", json={"kind": "home_assistant", "label": "", "base_url": HA_URL,
                                                    "token": HA_TOKEN}, headers=ORIGIN)
        assert got.status_code == 201, got.text
        yield made


def wanted(label: str, action: str, entity_id: str, name: str | None = None) -> dict[str, str | None]:
    return {"name": name, "label": label, "action": action, "entity_id": entity_id}


HALL = wanted("Hall light", "light.turn_on", "light.zq_hall")
PORCH = wanted("Porch off", "light.turn_off", "light.zq_porch")
NIGHT = wanted("Night", "scene.turn_on", "scene.zq_night")
