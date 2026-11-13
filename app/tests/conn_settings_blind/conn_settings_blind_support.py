"""Support for the blind per-connection-settings suite (`~/scratch/ashley/household-specific/design.txt`, sections 2 to
6, and the owner's decisions in the brief). Every guess about a name the item adds is listed here and made only here, so
a reconciler rewires one file. Everything else is code on main.

ASSUMPTIONS
 G1  Setting keys on a home_assistant connection: `reads` (list of actions), `service_reads` (list of actions),
     `household_reads` (object: action -> list of entity ids), `consequential_entities` (list of entity ids). Empty is
     an absent key, `[]` or `{}`; `empty()` reads all three.
 G2  Routes (design 4.1): `GET|PUT /api/connections/{id}/settings` (PUT body `{version, values}` replaces the whole
     object), `GET /api/connections/{id}/settings/history`, `GET /api/connections/{id}/catalogue?domains=a,b`.
     The settings body carries `version`, `values`, `schema` (a list); history `{items: [{key, changed_by,
     changed_at}]}`; the catalogue `{entities: [{id, ...}], actions: [{name, ...}]}`.
 G3  Statuses: stale version 409; a body the schema rejects 422; no session 401; another household's connection 404; a
     write from another site 403 (`ORIGIN` is the same site).
 G4  A well-formed entity id that is not in the house's catalogue is KEPT (design 2: "validation never reaches the
     service"); a malformed one (not `domain.object_id`) is 422.
 G5  Tables: `connection_settings(connection_id, values, version, ...)` and `connection_settings_log(connection_id,
     changed_at, ...)`, one log row per changed key; retention is enforced by the writer on a write, and the limit is
     between 30 and 500 days (the tests age rows to those two).
 G6  The log line is `connections.settings.changed` with `household`, `person`, `kind`, `connection`, `changed` (key
     names); it carries no entity id or value.
 G7  The reader entry is `ashley.wiring.tools(closers)[1](home)`, the tools over a `Home`, built per turn; the app's
     lifespan registers the settings service on the real database. A setting a person saves applies to the tools built
     for the next turn.
 G8  The settings migration is later than `drop_watch_grant`; it seeds the home_assistant connection of household 1
     (`seed.FALLBACK_HOUSEHOLD`) from the values shipped on main, and any other household's starts empty.
 G2 was wrong on the wire's names (`revision`, entries, `settings`, `changes`, `edited_by`, `entity_id`, repeated
     `domains`): `WireTranslator` below translates; no assertion changed.
 G10 The double answered a `todo.get_items` for every list whatever was asked, so a read of one listed list looked
     like a read of three: `AsksOnly` answers for the ids asked, as Home Assistant does.
 G11 The house held a `switch.plug` the catalogue assertions never expected (the route lists a domain whole); the
     fixture no longer has it. `changed_by` is the person's id (the app serves the person; the suite took either).
 G7 was wrong about the read point: `Tools.for_turn()` reads the settings once per turn, so `ask` calls it on the tools
     built over the home, as a turn does.
 G9  The catalogue route reads the house through `Homes.of(household_id).house` (a registered `Homes`).
"""

import base64
import json
import hashlib
import os
import secrets
from urllib.parse import parse_qsl, urlencode
from collections.abc import Callable, Coroutine, Generator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

import httpx2
import psycopg
from ashley import services
from ashley.channels.steps import NO_STEPS
from ashley.home_assistant.client import HomeAssistant
from ashley.home_assistant.homes import Home, Homes
from ashley.home_assistant.house import ActionInfo, Performed
from ashley.inference.model import ToolCall
from ashley.main import create_app
from ashley.people import admin
from ashley.senses.outside_record import OutsideRecord
from ashley.senses.proposal_payloads import Payload, Topic, encode
from ashley.senses.proposals import Proposal, ProposalRefused, Proposals
from ashley.api.person import SESSION_COOKIE
from ashley.settings import Settings
from ashley.tools.outside import Outside, Standing
from ashley import wiring
from fastapi.testclient import TestClient
from house_double_support import MemoryHouse, state
from outside_record_support import MemoryRecord
from httpx2 import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

PUBLIC = "https://ashley.test"
ORIGIN = {"origin": PUBLIC}
APP_KEY = base64.b64encode(os.urandom(32)).decode()
HA_URL, HA_TOKEN = "http://ha.test:8123", "long-lived-token-for-the-test-house"
LISTS = ("todo.inbox", "todo.family", "todo.to_do_list")
KEYS = ("reads", "service_reads", "household_reads", "consequential_entities")
CONVERSATION, TURN = 40, 100


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


def people_in(db_url: str) -> People:
    with psycopg.connect(db_url) as conn:
        home, other = admin.add_household(conn, "home", "America/Denver"), admin.add_household(conn, "other", "UTC")
        alana, sam, kim = (admin.add_person(conn, home, "Alana"), admin.add_person(conn, home, "Sam"),
                          admin.add_person(conn, other, "Kim"))
        return People(alana, sam, kim, home, other, {"alana": session(conn, alana, home, "a"),
                                                    "sam": session(conn, sam, home, "s"),
                                                    "kim": session(conn, kim, other, "k")})


class AsksOnly(MemoryHouse):
    """Home Assistant answers a `todo.get_items` for the lists asked about, as the real service does, not for every
    list the house has."""

    async def perform(self, action: str, ids: tuple[str, ...], data: Mapping[str, Any]) -> Performed:
        done = await super().perform(action, ids, data)
        if not isinstance(done.response, dict):
            return done
        return Performed(done.changed, {i: r for i, r in done.response.items() if i in ids})


def the_house() -> MemoryHouse:
    """Three lists, a lamp and a garage-door cover; `todo.get_items` answers as a read."""
    house = AsksOnly(things=[*(state(i, i, "1") for i in LISTS), state("switch.lamp", "Lamp", "off", device_class="switch"),
                                state("switch.fan_relay", "Relay", "off", device_class="switch")])
    house.catalogue = [ActionInfo("todo.get_items", "Items", {}, "only"), ActionInfo("switch.turn_on", "On", {}, "none"),
                       ActionInfo("script.find_person", "Locate", {}, "optional"),
                       ActionInfo("script.where", "Where", {}, "optional")]
    house.returns = {"todo.get_items": {i: {"items": [{"summary": "x"}]} for i in LISTS}}
    return house


class MemoryProposals(Proposals):
    """Proposals in a dict, for a held change to land in."""

    def __init__(self) -> None:
        self.rows: dict[tuple[int, str, int | None], Proposal[Any]] = {}

    async def propose[P: Payload](self, proposal: Proposal[P], ttl_s: float) -> int:
        name, _ = encode(proposal.payload)
        self.rows[(proposal.made_by, name, None if name == "outside" else proposal.conversation_id)] = proposal
        return len(self.rows)

    async def pending[P: Payload](self, made_by: int, conversation_id: int, topic: Topic[P]) -> Proposal[P] | None:
        return self.rows.get((made_by, topic.name, None if topic.scope == "person" else conversation_id))

    async def take[P: Payload](self, made_by: int, conversation_id: int, topic: Topic[P], turn_id: int,
                               ttl_s: float) -> Proposal[P]:
        raise ProposalRefused("none")

    async def find[P: Payload](self, proposal_id: int, topic: Topic[P]) -> Proposal[P] | None:
        raise AssertionError("not used")

    async def take_by_id[P: Payload](self, proposal_id: int, topic: Topic[P], made_by: int, turn_id: int,
                                     ttl_s: float) -> Proposal[P]:
        raise AssertionError("not used")


class FixedHomes(Homes):
    """Each household in `houses` has the one house given for it; `check` accepts any address."""

    def __init__(self, houses: Mapping[int, MemoryHouse]) -> None:
        self.houses = dict(houses)

    async def of(self, household_id: int) -> Home | None:
        house = self.houses.get(household_id)
        if house is None:
            return None
        client = HomeAssistant(httpx2.AsyncClient(transport=httpx2.MockTransport(lambda r: httpx2.Response(200, json={})),
                                                  base_url=HA_URL))
        return Home(household_id, client, house)

    async def check(self, base_url: str, token: str) -> None:
        return None


def _object(value: Any) -> dict[str, Any] | None:
    loose: Any = value
    return dict(loose) if isinstance(value, dict) else None


def _entries(values: Any) -> Any:
    """The blind suite's `{key: value}` as the wire's list of entries; a malformed value is carried as it is so the
    server refuses it."""
    table = _object(values)
    if table is None:
        return values
    entries: list[dict[str, Any]] = []
    for key, value in table.items():
        per = _object(value)
        if per is not None:
            entries.append({"key": key, "per_action": [{"action": a, "ids": i} for a, i in per.items()]})
        else:
            entries.append({"key": key, "ids": value})
    return entries


def _dict_of(entries: list[dict[str, Any]]) -> dict[str, Any]:
    return {e["key"]: ({a["action"]: a["ids"] for a in e["per_action"]} if e["per_action"] else e["ids"])
            for e in entries}


def _request_body(path: str, method: str, body: bytes) -> bytes:
    if method != "PUT" or not path.endswith("/settings"):
        return body
    try:
        sent: Any = json.loads(body)
    except ValueError:
        return body
    fields = _object(sent)
    if fields is None:
        return body
    out: dict[str, Any] = {k: v for k, v in fields.items() if k not in ("version", "values")}
    if "version" in fields:
        out["revision"] = fields["version"]
    if "values" in fields:
        out["values"] = _entries(fields["values"])
    return json.dumps(out).encode()


def _person_id(change: dict[str, Any]) -> Any:
    person: dict[str, Any] | None = change["edited_by"]
    return None if person is None else person["id"]


def _response_body(path: str, data: dict[str, Any]) -> dict[str, Any]:
    if path.endswith("/settings"):
        return {**data, "version": data["revision"], "schema": data["settings"], "values": _dict_of(data["values"])}
    if path.endswith("/settings/history"):
        return {**data, "items": [{**c, "changed_by": _person_id(c)} for c in data["changes"]]}
    if "/catalogue" in path:
        return {**data, "entities": [{**e, "id": e["entity_id"]} for e in data["entities"]]}
    return data


class WireTranslator:
    """G2 rewired, as middleware: the suite speaks `{version, values: {key: value}}`, `schema`, `items`, entity `id`
    and comma-separated `domains`; the app speaks `revision`, `values` as entries, `settings`, `changes`, `entity_id`
    and repeated `domains`. Only this translates; no assertion changed."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = str(scope.get("path", ""))
        if scope["type"] != "http" or not any(t in path for t in ("/settings", "/catalogue")):
            await self.app(scope, receive, send)
            return
        method = str(scope["method"])
        pairs = [(k, d) for k, v in parse_qsl(bytes(scope["query_string"]).decode())
                 for d in (v.split(",") if k == "domains" else [v])]
        scope = {**scope, "query_string": urlencode(pairs).encode()}
        chunks: list[bytes] = []
        while True:
            message = await receive()
            chunks.append(bytes(message.get("body", b"")))
            if not message.get("more_body", False):
                break
        body = _request_body(path, method, b"".join(chunks))

        async def replay() -> Message:
            return {"type": "http.request", "body": body, "more_body": False}

        start: Message = {}
        held: list[bytes] = []

        async def respond(message: Message) -> None:
            nonlocal start
            if message["type"] == "http.response.start":
                start = message
                return
            held.append(bytes(message.get("body", b"")))
            if message.get("more_body", False):
                return
            whole = b"".join(held)
            if start["status"] == 200:
                whole = json.dumps(_response_body(path, json.loads(whole))).encode()
            headers = [(k, v) for k, v in start["headers"] if k.lower() != b"content-length"]
            await send({**start, "headers": [*headers, (b"content-length", str(len(whole)).encode())]})
            await send({"type": "http.response.body", "body": whole})

        await self.app(scope, replay, respond)


@contextmanager
def app_client(db_url: str, people: People, houses: Mapping[int, MemoryHouse] | None = None) -> Generator[TestClient]:
    app = create_app(Settings(database_url=db_url, build_version="t", public_url=PUBLIC, connections_key=APP_KEY))
    with TestClient(WireTranslator(app), base_url=PUBLIC, follow_redirects=False) as client:
        services.register(Homes, FixedHomes(houses if houses is not None else {people.home: the_house(),
                                                                              people.other: the_house()}))
        services.register(OutsideRecord, MemoryRecord())
        services.register(Proposals, MemoryProposals())
        yield client


def as_(client: TestClient, people: People, who: str | None) -> None:
    client.cookies.clear()
    if who is not None:
        client.cookies.set(SESSION_COOKIE, people.tokens[who], domain="ashley.test")


def connect_ha(client: TestClient) -> int:
    """Add a Home Assistant connection for the signed-in household; its id."""
    got = client.post("/api/connections", json={"kind": "home_assistant", "label": "", "base_url": HA_URL,
                                                "token": HA_TOKEN}, headers=ORIGIN)
    assert got.status_code == 201, got.text
    return int(got.json()["id"])


def settings_url(cid: int) -> str:
    return f"/api/connections/{cid}/settings"


def read(client: TestClient, cid: int) -> Response:
    return client.get(settings_url(cid))


def write(client: TestClient, cid: int, values: Mapping[str, Any], version: int | None = None) -> Response:
    """Replace the settings with `values`, at `version` or the one read now."""
    at = version if version is not None else int(read(client, cid).json()["version"])
    return client.put(settings_url(cid), json={"version": at, "values": dict(values)}, headers=ORIGIN)


def values_of(client: TestClient, cid: int) -> dict[str, Any]:
    got = read(client, cid)
    assert got.status_code == 200, got.text
    return dict(got.json()["values"])


def empty(values: Mapping[str, Any], key: str) -> bool:
    return not values.get(key)


def on_app_loop[T](client: TestClient, work: Callable[[], Coroutine[Any, Any, T]]) -> T:
    """Run `work` on the app's own event loop, where its database pool lives."""
    assert client.portal is not None
    return client.portal.call(work)


async def ask(home: Home, action: str, ids: list[str], tool: str = "house_ask", tainted: str | None = None,
              data: str | None = None) -> tuple[str | None, str]:
    """One tool call in a fresh turn over the tools built for `home`: (the turn's taint after it, the reply text)."""
    closers: list[Callable[[], Coroutine[Any, Any, None]]] = []
    _, over, _ = wiring.tools(closers, "https://search.test")
    outside = Outside(await over(home).for_turn(), Standing(home.household_id, 7, private=True, agreeing=True), (CONVERSATION, TURN),
                      NO_STEPS, tainted)
    arguments: dict[str, object] = {"action": action, "ids": ids, **({} if data is None else {"data": data})}
    got = await outside.call(ToolCall("c1", tool, arguments))
    for close in closers:
        await close()
    return outside.tainted, got.content


async def home_of(household_id: int) -> Home:
    home = await services.get(Homes).of(household_id)
    assert home is not None
    return home
