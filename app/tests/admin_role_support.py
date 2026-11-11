"""The admin role's tests share this: a deployment of two households in a real database (the first with three people,
each with an OIDC account; the second with one), the app over it with a fake provider, and reads of who is an admin
straight from the database."""

import hashlib
import secrets
from collections.abc import Generator
from dataclasses import dataclass

import psycopg
from ashley import services
from ashley.api.person import SESSION_COOKIE
from ashley.main import create_app
from ashley.people import admin
from ashley.settings import Settings
from ashley.signin.oidc import Oidc
from ashley.signin.provider import Client
from contract.conversations_support import scalar
from fastapi.testclient import TestClient
from signin_support import CLIENT, ISSUER, FakeIdp, oidc_for

PUBLIC = "https://ashley.test"
ORIGIN = {"origin": PUBLIC}
GROUP = "deployment-admins"


@dataclass(frozen=True)
class Deployment:
    """`first` is household 1 and `other` household 2; `ana`, `ben` and `cy` are the first's people in id order, `kim`
    the other's. Each person's OIDC sub is `sub-<name>`."""

    url: str
    first: int
    other: int
    ana: int
    ben: int
    cy: int
    kim: int


def deployment(url: str) -> Deployment:
    with psycopg.connect(url) as conn:
        first, other = admin.add_household(conn, "home", "UTC"), admin.add_household(conn, "other", "UTC")
        ana, ben, cy = (admin.add_person(conn, first, n) for n in ("Ana", "Ben", "Cy"))
        kim = admin.add_person(conn, other, "Kim")
        for person, name in ((ana, "ana"), (ben, "ben"), (cy, "cy"), (kim, "kim")):
            admin.add_account(conn, person, "oidc", f"sub-{name}")
    assert first == 1, "the first household must be household 1"
    return Deployment(url, first, other, ana, ben, cy, kim)


def session_for(url: str, person: int, admin_now: bool = False) -> str:
    """A live session for the person's OIDC account, made in the database as a sign-in would (`admin_now` as the group
    said at it), and its token."""
    token = secrets.token_urlsafe(16)
    scalar(url, "INSERT INTO sessions (token_sha256, account_id, household_id, expires_at, admin) "
                "SELECT %s, id, household_id, now() + interval '1 day', %s FROM accounts "
                "WHERE person_id = %s AND system = 'oidc' RETURNING id",
           (hashlib.sha256(token.encode()).digest(), admin_now, person))
    return token


def set_admin(url: str, person: int, value: bool = True) -> None:
    scalar(url, "UPDATE people SET admin = %s WHERE id = %s RETURNING id", (value, person))


def admins(url: str) -> list[int]:
    with psycopg.connect(url) as conn:
        return [r[0] for r in conn.execute("SELECT id FROM people WHERE admin ORDER BY id").fetchall()]


def app_client(url: str, fake: FakeIdp, admin_group: str = "") -> Generator[TestClient]:
    """The app over `url` signing in through `fake`, with `admin_group` as `ADMIN_GROUP`."""
    app = create_app(Settings(database_url=url, build_version="t", oidc_issuer=ISSUER, oidc_client_id=CLIENT.client_id,
                              oidc_client_secret=CLIENT.client_secret, public_url=PUBLIC, admin_group=admin_group))
    client = Client(CLIENT.issuer, CLIENT.client_id, CLIENT.client_secret, CLIENT.redirect_uri, admin_group)
    services.register(Oidc, oidc_for(fake, client))
    with TestClient(app, base_url=PUBLIC, follow_redirects=False) as c:
        yield c
    services.unregister(Oidc)


def sign_in(client: TestClient, fake: FakeIdp, sub: str, groups: list[str] | None = None) -> str:
    """Sign a fresh browser in as the account `sub`, the provider's ID token carrying `groups` (no claim when None), and
    answer its session token; `client` is then that browser. An earlier session stays open (`as_browser` returns to it)."""
    client.cookies.clear()
    fake.sub = sub
    fake.claims = {} if groups is None else {"groups": groups}
    started = client.get("/api/auth/signin", params={"next": "/"})
    assert started.status_code == 302
    code, state = fake.authorize(started.headers["location"])
    done = client.get("/api/auth/callback", params={"code": code, "state": state})
    assert (done.status_code, done.headers["location"]) == (302, "/"), done.headers.get("location")
    token = client.cookies.get(SESSION_COOKIE)
    assert token
    return token


def as_browser(client: TestClient, token: str) -> None:
    client.cookies.clear()
    client.cookies.set(SESSION_COOKIE, token, domain="ashley.test")


def me_admin(client: TestClient) -> bool:
    me = client.get("/api/me")
    assert me.status_code == 200, me.text
    admin_now: bool = me.json()["person"]["admin"]
    return admin_now
