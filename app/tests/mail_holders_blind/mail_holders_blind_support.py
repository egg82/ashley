"""Blind contract tests for holders and resources (decisions.md, "Who holds a connection, and who sees what it
reaches", build part 3): the real app on a real database, with test kinds that declare their holders and list their
resources from a fake service (`Boxes`). Everything the design does not name is guessed once, in ASSUMPTIONS below; a
test never guesses on its own. The same list, with the design sentence each rests on, is in assumptions.txt beside
the notes of this suite.

ASSUMPTIONS:

H1  `ConnectionKind.personal` is replaced by `holders: frozenset[Holder]`, `Holder = Literal["household", "person"]`
    in `ashley.connections.model`; a kind also declares `resources: Callable[[Opened], Awaitable[tuple[Resource, ...]]]`
    and `Resource(ref, kind, name)` (also in `ashley.connections.model`, `kind` being `"mailbox"`) is what it returns.
    Rests on "`ConnectionKind.personal` becomes `holders`, the set of `household` and `person`" and "`ConnectionKind`
    gains `resources(opened)`".
H2  The wire `HouseholdConnection` gains `holder` (`household` or `person`) and `resources`, a list of
    `{ref, kind, name, shared}`; `ConnectionKindInfo` gains `holders`, a list. `GET /api/connections` is "the room is
    opened", so it lists again through the kind. Rests on "again whenever the room is opened" and "each resource of a
    personal connection is kept until its owner shares it".
H3  `POST /api/connections` with no holder is held by the person where the kind allows it, else by the household. Rests
    on "A connection's `person_id` stays the one field that says which" and the OAuth start's default holder `person`.
H4  `PATCH /api/connections/{id}` with `{"holder": "household" | "person"}` answers 200 with the connection; 404 for
    one the caller cannot see; 403 `forbidden` when a member who is not `added_by` takes a handed-over one back; 422
    `unsupported` when the kind does not allow that holder; 409 `too_many` past the kind's `most` for the new holder; 422
    for any other holder. The design names only `added_by` and 409 `too_many`. The statuses follow the routes beside it.
H5  A move reseals the refresh token or pasted secret and the sealed access token, both bound by
    `ashley.connections.sealing.bound_to(household, kind, new person or None)`. Rests on "Moving reseals the secret bound
    to its new holder, in the same transaction, since a secret is sealed bound to household, kind and person".
H6  `PATCH /api/connections/{id}/resources/{ref}` with `{"shared": bool}` answers 200 with the resource wire shape; 404 for
    a connection the caller cannot see (so for anyone but the owner of a person-held one) or a ref it does not list; a
    4xx and no change for keeping a resource of a household-held connection. Rests on "owner only" and "Every resource of
    a household connection is shared".
H7  `connection_resources` has the columns the design names (`connection_id`, `ref`, `kind`, `name`, `shared`); `shared`,
    `kind` and `ref` are NOT NULL; the migration file is named `*_connection_resources.py`; after it a kind of `gitlab`
    can be stored with a NULL `person_id`. Rests on "The migration adds `connection_resources`" and "The check on
    `person_id` that `personal` implied moves to the service".
H8  The gate is the service `ashley.connections.resources.ConnectionResources`, reached through the locator, with
    `usable(inbound, changing=False)` answering the resources (each with `connection_id` and `ref`) of kind `mailbox` the
    turn may use: reading, or changing. The design names no service; it names the table of the gate and
    `audience.owner_alone`.
H9  `connections.moved` carries `connection` (id) and `holder`; `connections.resource_shared` carries `connection` and
    `shared`, as the design's "(connection id, holder or shared)" and the existing `connection=` field.
H10 A resource first seen on a reread is kept for a person-held connection, shared for a household-held one. Rests on
    "Each resource of a personal connection is kept until its owner shares it".
H11 The household's connection that its members may open for a shared resource is out of scope: the design does not say how
    a turn of another member opens the owner's login, so no test opens a person's connection as someone else.
"""

import base64
import hashlib
import logging
import os
import re
import secrets
from collections.abc import Awaitable, Callable, Generator
from dataclasses import dataclass, field
from typing import Any, TypeVar

import httpx2
import psycopg
import pytest
from ashley import services
from ashley.api.person import SESSION_COOKIE
from ashley.channels.audience import use_of
from ashley.channels.model import Inbound
from ashley.connections.connections import Connections
from ashley.connections.kinds import ConnectionKind, ConnectionKinds, Refusal
from ashley.connections.model import Holder, Listed, Opened
from ashley.connections.resources import ConnectionResources
from ashley.connections.sealing import Sealer, Unsealable, bound_to, key_from
from ashley.main import create_app
from ashley.people import admin
from ashley.settings import Settings
from fastapi.testclient import TestClient

T = TypeVar("T")
PUBLIC = "https://ashley.test"
ORIGIN = {"origin": PUBLIC}
APP_KEY = base64.b64encode(os.urandom(32)).decode()
URL = "https://music.test"
SECRET = "holder-secret-0001"
REASONS: tuple[Refusal, ...] = ("bad_url", "key_refused", "unreachable", "wrong_service")


@dataclass
class Boxes:
    """The fake service every test kind lists resources from: `refs` and `names` are what it says now; `calls` counts
    its answers and `secrets` the secret it was opened with each time."""

    refs: list[str] = field(default_factory=lambda: ["alana@home.test"])
    names: dict[str, str] = field(default_factory=dict[str, str])
    calls: int = 0
    secrets: list[str] = field(default_factory=list[str])

    async def __call__(self, opened: Opened) -> tuple[Listed, ...]:
        self.calls += 1
        self.secrets.append(opened.secret)
        return tuple(Listed(r, "mailbox", self.names.get(r, f"Inbox of {r}")) for r in self.refs)


async def _ok(base_url: str, secret: str, person_id: int) -> Refusal | None:
    return None


def kind(name: str, most: int, holders: frozenset[Holder], boxes: Boxes) -> ConnectionKind:
    return ConnectionKind(name=name, title=name.title(), what="mail", blurb="blurb", connected="Now connected.",
                          removed="Now removed.", holders=holders, schemes=frozenset({"https"}),
                          address_placeholder="https://mail.example", secret_field="token", secret_label="Token",
                          secret_noun="token", check=_ok, refusals={r: f"{name} says {r}" for r in REASONS},
                          ports=frozenset(), most=most, resources=boxes)


BOTH = "both"
ONE = "one"
HOME = "homeonly"
OWN = "ownonly"


def kinds_for(boxes: Boxes) -> tuple[ConnectionKind, ...]:
    """`both` is held either way, two per owner; `one` either way, one per owner; `homeonly` the household's;
    `ownonly` a person's."""
    either: frozenset[Holder] = frozenset({"household", "person"})
    home: frozenset[Holder] = frozenset({"household"})
    own: frozenset[Holder] = frozenset({"person"})
    return (kind(BOTH, 2, either, boxes), kind(ONE, 1, either, boxes), kind(HOME, 2, home, boxes),
            kind(OWN, 2, own, boxes))


@dataclass(frozen=True)
class People:
    url: str
    home: int
    other: int
    alana: int
    sam: int
    kim: int
    tokens: dict[str, str]


def _session(conn: psycopg.Connection, person: int, household: int, sub: str) -> str:
    account = admin.add_account(conn, person, "authentik", sub)
    token = secrets.token_urlsafe(16)
    conn.execute("INSERT INTO sessions (token_sha256, account_id, household_id, expires_at) "
                 "VALUES (%s, %s, %s, now() + interval '1 day')",
                 (hashlib.sha256(token.encode()).digest(), account, household))
    return token


def make_people(url: str) -> People:
    with psycopg.connect(url) as conn:
        home, other = admin.add_household(conn, "home", "America/Denver"), admin.add_household(conn, "other", "UTC")
        alana, sam, kim = (admin.add_person(conn, home, "Alana"), admin.add_person(conn, home, "Sam"),
                          admin.add_person(conn, other, "Kim"))
        return People(url, home, other, alana, sam, kim, {"alana": _session(conn, alana, home, "a"),
                                                         "sam": _session(conn, sam, home, "s"),
                                                         "kim": _session(conn, kim, other, "k")})


def as_(client: TestClient, people: People, who: str) -> None:
    client.cookies.set(SESSION_COOKIE, people.tokens[who], domain="ashley.test")


def app_client(url: str, boxes: Boxes) -> Generator[TestClient]:
    """The real app on the database, with only the test kinds registered once it has started."""
    app = create_app(Settings(database_url=url, build_version="t", public_url=PUBLIC, connections_key=APP_KEY))
    with TestClient(app, base_url=PUBLIC, follow_redirects=False) as c:
        services.register(ConnectionKinds, ConnectionKinds(kinds_for(boxes)))
        yield c


def in_app(client: TestClient, call: Callable[[], Awaitable[T]]) -> T:
    """Run `call` on the event loop the app's services live on."""
    portal = client.portal
    assert portal is not None
    return portal.call(call)


# --- the routes ----------------------------------------------------------------------------------------------------


def make(client: TestClient, kind_name: str = BOTH, label: str = "a", secret: str = SECRET) -> int:
    got = client.post("/api/connections", json={"kind": kind_name, "label": label, "base_url": URL, "token": secret},
                      headers=ORIGIN)
    assert got.status_code == 201, got.text
    return int(got.json()["id"])


def holder_of(body: dict[str, Any]) -> str:
    """Who holds a connection, from the wire's `personal` (the build names no `holder` field)."""
    return "person" if body["personal"] else "household"


def listing(client: TestClient) -> dict[int, dict[str, Any]]:
    got = client.get("/api/connections")
    assert got.status_code == 200, got.text
    return {c["id"]: c for c in got.json()["connections"]}


def resources_of(client: TestClient, connection_id: int) -> dict[str, dict[str, Any]]:
    """What the room shows once it has been opened twice: the build answers an opening from stored rows and reads each
    service after the answer, so what the service says now shows from the next opening."""
    listing(client)
    return {r["ref"]: r for r in listing(client)[connection_id]["resources"]}


def hand(client: TestClient, connection_id: int, holder: str, headers: dict[str, str] | None = None) -> httpx2.Response:
    return client.patch(f"/api/connections/{connection_id}", json={"holder": holder},
                        headers=ORIGIN if headers is None else headers)


def share(client: TestClient, connection_id: int, ref: str, shared: bool = True,
          headers: dict[str, str] | None = None) -> httpx2.Response:
    return client.patch(f"/api/connections/{connection_id}/resources/{ref}", json={"shared": shared},
                        headers=ORIGIN if headers is None else headers)


def shared_with_alana_kept(client: TestClient, boxes: Boxes, kind_name: str = BOTH) -> int:
    """A person-held connection listing `kept@a.test` and `shared@a.test`, the second shared with the household."""
    boxes.refs = ["kept@a.test", "shared@a.test"]
    cid = make(client, kind_name)
    assert share(client, cid, "shared@a.test").status_code == 200
    return cid


# --- the database --------------------------------------------------------------------------------------------------


def one(url: str, query: str, params: tuple[object, ...] = ()) -> Any:
    with psycopg.connect(url, autocommit=True) as conn:
        row = conn.execute(query.encode(), params).fetchone()
    assert row is not None
    return row[0]


def person_of(url: str, connection_id: int) -> int | None:
    found = one(url, "SELECT person_id FROM connections WHERE id = %s", (connection_id,))
    return None if found is None else int(found)


def stored(url: str, connection_id: int) -> list[tuple[str, str, str, bool]]:
    with psycopg.connect(url, autocommit=True) as conn:
        return [(r[0], r[1], r[2], r[3]) for r in conn.execute(
            "SELECT ref, kind, name, shared FROM connection_resources WHERE connection_id = %s ORDER BY ref",
            (connection_id,)).fetchall()]


def snapshot(url: str, connection_id: int) -> tuple[Any, ...]:
    """Every column of the row and of its resources, so 'nothing was written' is a comparison."""
    with psycopg.connect(url, autocommit=True) as conn:
        row = conn.execute("SELECT * FROM connections WHERE id = %s", (connection_id,)).fetchone()
        res = conn.execute("SELECT * FROM connection_resources WHERE connection_id = %s ORDER BY ref",
                           (connection_id,)).fetchall()
    return (row, res)


def sealed(url: str, connection_id: int) -> tuple[bytes, bytes | None]:
    with psycopg.connect(url, autocommit=True) as conn:
        row = conn.execute("SELECT secret, access_token FROM connections WHERE id = %s", (connection_id,)).fetchone()
    assert row is not None
    return bytes(row[0]), None if row[1] is None else bytes(row[1])


def opens_as(url: str, people: People, connection_id: int, column: str, kind_name: str, person: int | None) -> str | None:
    """What the stored sealed `column` ('secret' or 'access_token') opens to when bound to `person` (None: the
    household), or None when it does not open."""
    with psycopg.connect(url, autocommit=True) as conn:
        row = conn.execute(f"SELECT {column} FROM connections WHERE id = %s".encode(), (connection_id,)).fetchone()
    assert row is not None and row[0] is not None
    try:
        return Sealer({1: key_from(APP_KEY)}).open(bytes(row[0]), bound_to(people.home, kind_name, person))
    except Unsealable:
        return None


def opened_secret(client: TestClient, people: People, connection_id: int, who: str) -> str | None:
    person = getattr(people, who)

    async def read() -> str | None:
        found = await services.get(Connections).opened(connection_id, people.home, person)
        return None if found is None else found.secret

    return in_app(client, read)


# --- the turn ------------------------------------------------------------------------------------------------------


def web(home: int, person: int, device_id: int | None = None) -> Inbound:
    """A person's own web chat: the channel names the speaker and only they read the reply. With `device_id`, a screen
    shows the thread too."""
    return Inbound(household_id=home, thread=f"person:{person}:web", text="hi", kind="chat", medium="text",
                   audience="owner", speaker_id=person, shared=False, place=None, channel="web", device_id=device_id)


def satellite(home: int, heard_as: int | None = None) -> Inbound:
    """A voice satellite: no speaker named by the channel, a voice match at most a hint."""
    return Inbound(household_id=home, thread="device:1", text="hi", kind="command", medium="spoken",
                   audience="present", speaker_id=None, shared=True, place="kitchen", channel="voice",
                   heard_as=heard_as)


def tablet(home: int) -> Inbound:
    return Inbound(household_id=home, thread="device:2", text="hi", kind="command", medium="text", audience="present",
                   speaker_id=None, shared=True, place="hallway", channel="device", device_id=2)


def shared_channel(home: int, person: int | None) -> Inbound:
    """A household's Discord channel whose message names its author."""
    return Inbound(household_id=home, thread="discord:channel:1", text="hi", kind="chat", medium="text",
                   audience="household", speaker_id=person, shared=True, place=None, channel="discord")


def usable(client: TestClient, inbound: Inbound, changing: bool = False) -> set[tuple[int, str]]:
    async def ask() -> set[tuple[int, str]]:
        found = await services.get(ConnectionResources).usable(use_of(inbound), changing)
        return {(u.connection.id, u.resource.ref) for u in found}

    return in_app(client, ask)


def refs(client: TestClient, inbound: Inbound, changing: bool = False) -> set[str]:
    return {ref for _, ref in usable(client, inbound, changing)}


# --- logs ----------------------------------------------------------------------------------------------------------


def all_logs(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)


def log_text(caplog: pytest.LogCaptureFixture) -> str:
    return "\n".join(f"{r.name} {r.msg} {getattr(r, 'fields', {})!r} {r.exc_text or ''}" for r in caplog.records)


def lines(caplog: pytest.LogCaptureFixture, event: str) -> list[dict[str, Any]]:
    return [dict(getattr(r, "fields", {})) for r in caplog.records if r.msg == event]


def words(text: str) -> set[str]:
    return set(re.split(r"\W+", text))
