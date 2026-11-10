"""Helpers for the blind Discord-link contract tests: an app over a real database with a fake `DiscordOAuth` behind the
locator, three people (A and B in one household, C in another) each signed in with their own session cookie, and the
browser's two legs by hand (start, then Discord's return). The contract is `ashley.api.models`, `openapi.json`,
`ashley.signin.discord`'s port and `decisions.md`, "A person links their own Discord account"."""

import base64
import hashlib
import secrets
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

import psycopg
from ashley import services
from ashley.main import create_app
from ashley.settings import Settings
from ashley.signin.discord import CALLBACK_PATH, DiscordOAuth, DiscordUser, LinkFailed, LinkUnavailable
from ashley.signin.oidc import Oidc
from conversations_support import household, person
from fastapi.testclient import TestClient
from people_support import account
from signin_contract_support import SITE
from signin_support import CLIENT, ISSUER, FakeIdp, oidc_for

REDIRECT = SITE + CALLBACK_PATH
WRITE = {"Origin": SITE}


def s256(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


def query_of(url: str) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}


@dataclass
class FakeDiscord(DiscordOAuth):
    """Discord as a browser meets it. `approve` plays the person clicking Authorize as `user`: it reads the URL the app
    sent the browser to and returns the (code, state) Discord would put on the callback. `identify` redeems a code only
    with the verifier whose S256 is the challenge sent with that state, once. `mode` other than `ok` makes `identify`
    refuse (`refused`) or fail to reach Discord (`down`)."""

    mode: str = "ok"
    on: bool = True
    challenges: dict[str, str] = field(default_factory=dict[str, str])
    codes: dict[str, tuple[DiscordUser, str]] = field(default_factory=dict[str, tuple[DiscordUser, str]])
    identified: list[str] = field(default_factory=list[str])

    def configured(self) -> bool:
        return self.on

    async def authorize_url(self, state: str, challenge: str) -> str:
        self.challenges[state] = challenge
        return "https://discord.test/oauth2/authorize?" + urlencode({
            "client_id": "cid", "response_type": "code", "scope": "identify", "state": state,
            "redirect_uri": REDIRECT, "code_challenge": challenge, "code_challenge_method": "S256"})

    async def identify(self, code: str, verifier: str) -> DiscordUser:
        self.identified.append(code)
        if self.mode == "down":
            raise LinkUnavailable("Discord could not be reached")
        redeemed = self.codes.pop(code, None)
        if self.mode == "refused" or redeemed is None:
            raise LinkFailed("Discord refused the code")
        user, state = redeemed
        if self.challenges.get(state) != s256(verifier):
            raise LinkFailed("the verifier does not match the challenge")
        return user

    def approve(self, url: str, user: DiscordUser) -> tuple[str, str]:
        query = query_of(url)
        assert query["scope"] == "identify" and query["redirect_uri"] == REDIRECT
        code = secrets.token_urlsafe(12)
        self.codes[code] = (user, query["state"])
        return code, query["state"]


@dataclass
class Web:
    """The app, its fake Discord and each person's cookies. Every call names who makes it (None: nobody signed in), so
    a request carries exactly that person's cookie and no other."""

    client: TestClient
    url: str
    discord: FakeDiscord
    who: dict[str, int]
    hh: dict[str, int]
    cookies: dict[str, str]

    def call(self, name: str | None, method: str, path: str, headers: dict[str, str] | None = None, **kw: Any) -> Any:
        sent = dict(headers or {})
        if name is not None:
            sent["Cookie"] = f"__Host-ashley_session={self.cookies[name]}"
        self.client.cookies.clear()
        return self.client.request(method, path, headers=sent, **kw)

    def accounts(self, name: str | None) -> Any:
        return self.call(name, "GET", "/api/accounts")

    def start(self, name: str | None, headers: dict[str, str] | None = None, **kw: Any) -> Any:
        return self.call(name, "POST", "/api/accounts/discord/link", WRITE if headers is None else headers, **kw)

    def callback(self, name: str | None, **params: str) -> Any:
        return self.call(name, "GET", "/api/accounts/discord/callback", params=params)

    def unlink(self, name: str | None, account_id: int, headers: dict[str, str] | None = None) -> Any:
        return self.call(name, "DELETE", f"/api/accounts/{account_id}", WRITE if headers is None else headers)

    def begin(self, name: str, user: DiscordUser) -> tuple[str, str]:
        """Start a link as `name` and let `user` authorize it: the (code, state) for the callback."""
        started = self.start(name)
        assert started.status_code == 201, started.text
        return self.discord.approve(started.json()["authorize_url"], user)

    def link(self, name: str, user: DiscordUser, as_: str | None = None) -> str:
        """The whole round trip, the callback made by `as_` (default `name`); where it landed."""
        code, state = self.begin(name, user)
        return landed(self.callback(name if as_ is None else as_, code=code, state=state))

    def discord_rows(self) -> list[tuple[int, str]]:
        """(person_id, external_id) of every stored Discord account."""
        with psycopg.connect(self.url) as conn:
            return conn.execute(b"SELECT person_id, external_id FROM accounts WHERE system = 'discord' "
                                b"ORDER BY id").fetchall()

    def pending(self) -> int:
        with psycopg.connect(self.url) as conn:
            row = conn.execute(b"SELECT count(*) FROM link_pending").fetchone()
        assert row is not None
        return int(row[0])


def landed(response: Any) -> str:
    """The `link` outcome a callback sent the browser to; fails the test unless it is a 302 to `/connections?link=...`."""
    assert response.status_code == 302, response.status_code
    parts = urlsplit(str(response.headers["location"]))
    assert parts.netloc in ("", urlsplit(SITE).netloc) and parts.path == "/connections", response.headers["location"]
    return parse_qs(parts.query)["link"][0]


def settings(url: str, discord: bool = True) -> Settings:
    base = {"build_version": "dev", "database_url": url, "public_url": SITE, "oidc_issuer": ISSUER,
            "oidc_client_id": CLIENT.client_id, "oidc_client_secret": CLIENT.client_secret}
    if discord:
        base |= {"discord_oauth_client_id": "cid", "discord_oauth_client_secret": "csecret"}
    return Settings(**base)


@contextmanager
def web(url: str, discord: bool = True, fake: bool = True) -> Generator[Web]:
    """A and B in `home` and C in `other`, each with an OIDC account and a session; the accounts and Discord
    port as the settings wire them, or `fake` standing in for Discord."""
    hh = {"home": household(url, "home"), "other": household(url, "other")}
    who = {"A": person(url, hh["home"], "A"), "B": person(url, hh["home"], "B"), "C": person(url, hh["other"], "C")}
    idp = FakeIdp()
    stand_in = FakeDiscord()
    services.unregister(DiscordOAuth)
    try:
        with TestClient(create_app(settings(url, discord)), base_url=SITE, follow_redirects=False) as client:
            services.register(Oidc, oidc_for(idp))
            if fake:
                services.register(DiscordOAuth, stand_in)
            cookies: dict[str, str] = {}
            for name, home in (("A", "home"), ("B", "home"), ("C", "other")):
                account(url, hh[home], who[name], "oidc", f"sub-{name}")
                idp.sub = f"sub-{name}"
                client.cookies.clear()
                started = client.get("/api/auth/signin")
                code, state = idp.authorize(started.headers["location"])
                assert client.get("/api/auth/callback", params={"code": code, "state": state}).status_code == 302
                cookies[name] = client.cookies["__Host-ashley_session"]
            yield Web(client, url, stand_in, who, hh, cookies)
    finally:
        services.unregister(DiscordOAuth)
