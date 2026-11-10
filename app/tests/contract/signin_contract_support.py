"""Helpers for the blind sign-in contract tests: an app over a real database with the fake provider wired in, a
browser that walks the sign-in redirects by hand, and a way to let time pass. The contract is `ashley.api.signin`'s
docstring, `openapi.json`, `signin.json` and `decisions.md`, "People sign in through OIDC"."""

import io
import os
from collections.abc import Generator
from contextlib import contextmanager, redirect_stdout
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import patch
from urllib.parse import urlsplit

import psycopg
from ashley import services
from ashley.main import create_app
from ashley.settings import Settings
from ashley.signin import __main__ as signin_cli
from ashley.signin.oidc import Oidc
from conversations_support import household, person
from fastapi.testclient import TestClient
from people_support import account
from signin_support import CLIENT, ISSUER, FakeIdp, oidc_for

SITE = "https://ashley.test"
FAILED = "/?signin=failed"
UNMAPPED = "/?signin=unmapped"


def settings(database_url: str, oidc: bool = True) -> Settings:
    if not oidc:
        return Settings(build_version="dev", database_url=database_url, public_url=SITE)
    return Settings(build_version="dev", database_url=database_url, public_url=SITE, oidc_issuer=ISSUER, oidc_client_id=CLIENT.client_id,
                    oidc_client_secret=CLIENT.client_secret)


def site_path(location: str) -> str:
    """`location` as a path and query on this site; fails the test if it names another host."""
    parts = urlsplit(location)
    assert parts.netloc in ("", urlsplit(SITE).netloc), f"redirect leaves the site: {location!r}"
    assert parts.scheme in ("", "https"), f"redirect scheme: {location!r}"
    return parts.path + (f"?{parts.query}" if parts.query else "")


@dataclass
class Browser:
    """One browser at the app: its cookie jar is the TestClient's."""

    client: TestClient
    fake: FakeIdp
    url: str
    state_cookies: set[str] = field(default_factory=set[str])

    def start(self, next_path: str | None = None) -> Any:
        params = {} if next_path is None else {"next": next_path}
        r = self.client.get("/api/auth/signin", params=params)
        self.state_cookies |= {c.split("=")[0] for c in set_cookies(r)}
        return r

    def callback(self, code: str, state: str) -> Any:
        return self.client.get("/api/auth/callback", params={"code": code, "state": state})

    def signin(self, next_path: str | None = None) -> Any:
        """The whole round trip; returns the callback's response."""
        started = self.start(next_path)
        assert started.status_code == 302, started.status_code
        code, state = self.fake.authorize(started.headers["location"])
        return self.callback(code, state)

    def me(self) -> Any:
        return self.client.get("/api/me")

    def signout(self, headers: dict[str, str] | None = None) -> Any:
        return self.client.post("/api/auth/signout", headers={"Origin": SITE, **(headers or {})})

    def session_cookies(self) -> dict[str, str]:
        return {k: v for k, v in self.client.cookies.items() if k.startswith("__Host-") and k not in self.state_cookies}


def set_cookies(response: Any) -> list[str]:
    return list(response.headers.get_list("set-cookie"))


def landed(response: Any) -> str:
    """Where a callback sent the browser, as a site path."""
    assert response.status_code == 302, response.status_code
    return site_path(response.headers["location"])


def map_account(url: str, sub: str, name: str = "Alana") -> int:
    hh = household(url)
    pid = person(url, hh, name)
    account(url, hh, pid, "oidc", sub)
    return pid


@contextmanager
def browser(url: str, fake: FakeIdp | None = None, **kwargs: Any) -> Generator[Browser]:
    fake = fake or FakeIdp()
    with TestClient(create_app(settings(url)), base_url=SITE, follow_redirects=False, **kwargs) as client:
        services.register(Oidc, oidc_for(fake))
        yield Browser(client, fake, url)


def let_time_pass(url: str, table: str, seconds: int) -> None:
    """Shift every timestamp in `table` back, which is what the clock moving forward looks like to the rows. The
    contract gives the database's clock the final say and no clock to inject, so this is the only way to age a row."""
    with psycopg.connect(url, autocommit=True) as conn:
        cols = [str(r[0]) for r in conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_schema = 'public' AND table_name = %s "
            "AND data_type LIKE 'timestamp%%'", (table,)).fetchall()]
        assert cols, f"{table} has no timestamp columns (is the table name still right?)"
        sets = ", ".join(f'"{c}" = "{c}" - make_interval(secs => {seconds})' for c in cols)
        rows = conn.execute(f"UPDATE {table} SET {sets}".encode()).rowcount
        assert rows >= 1, f"{table} had no rows to age"


def count(url: str, table: str) -> int:
    with psycopg.connect(url, autocommit=True) as conn:
        row = conn.execute(f"SELECT count(*) FROM {table}".encode()).fetchone()
    assert row is not None
    return int(row[0])


def unmapped_listing(url: str) -> str:
    """What `python -m ashley.signin unmapped` prints for the admin."""
    out = io.StringIO()
    with patch.dict(os.environ, {"DATABASE_URL": url}), redirect_stdout(out):
        code = signin_cli.main(["unmapped"])
    assert code == 0, code
    return out.getvalue()


