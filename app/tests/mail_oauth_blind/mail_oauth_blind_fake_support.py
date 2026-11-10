"""A fake Google OAuth2 provider at its HTTP boundary, with no import from `ashley`: `install` makes every
`httpx2.AsyncClient` request go to `FakeGoogle.handle` instead of the network, and records it. The provider behaves
as Google's documentation says: a code is single use and redeemed only with the verifier whose S256 challenge it was
issued for; the token endpoint authenticates the client; a refresh token that was never issued, or was revoked, is
`invalid_grant`; userinfo answers only for an access token it issued."""

import base64
import hashlib
import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx2
import pytest

CLIENT_ID = "gcid-0001.apps.googleusercontent.test"
CLIENT_SECRET = "gsecret-0001-CLIENTSECRET"
DAY = 86_400


def s256(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


def carries(text: str, secret: str) -> bool:
    """Whether `text` holds `secret` as written or as the hex of its bytes (a bytea column prints as hex)."""
    return secret in text or secret.encode().hex() in text


def holds_verifier(text: str, challenge: str) -> bool:
    """Whether some word of `text`, or the bytes a hex word spells, is the PKCE verifier `challenge` commits to."""
    for word in re.split(r"[^A-Za-z0-9\-._~\\]+", text):
        word = word.removeprefix("\\x")
        candidates = [word]
        if len(word) % 2 == 0 and re.fullmatch(r"[0-9a-f]+", word):
            candidates.append(bytes.fromhex(word).decode(errors="replace"))
        if any(s256(c) == challenge for c in candidates if c):
            return True
    return False


@dataclass(frozen=True)
class Seen:
    """One request the fake saw: `kind` is `token`, `userinfo`, `revoke` or `stray` (a host that is not Google's)."""

    kind: str
    method: str
    host: str
    path: str
    form: dict[str, str]
    bearer: str


@dataclass
class Grant:
    challenge: str
    redirect_uri: str
    scopes: tuple[str, ...]
    email: str


@dataclass
class FakeGoogle:
    """What the provider does next. `rotate` makes each refresh answer a new refresh token (as Microsoft does), the old one
    refused from then on under `strict_rotation` and still accepted otherwise (the grace given concurrent refreshes); off, a refresh answers none (as Google does). `expires_in` is what every token answer says.
    `refuse_refresh`, `refresh_status` (an answer that is not a refusal of the grant) and `refresh_down` shape the
    refresh grant; `refuse_code`, `omit_refresh` and `grant_scopes` the first one; `userinfo` is `ok`, `unauthorized`,
    `down` or `no_email`; `always_email` makes userinfo name the email even when the `email` scope was not granted.
    `in_refresh` runs once, inside the first refresh request, after the refresh token has been checked and before the
    answer: another pod's whole refresh happens there."""

    expires_in: int = DAY
    rotate: bool = False
    strict_rotation: bool = False
    refuse_refresh: bool = False
    refresh_status: int | None = None
    refresh_down: bool = False
    refuse_code: bool = False
    omit_refresh: bool = False
    grant_scopes: tuple[str, ...] | None = None
    userinfo: str = "ok"
    always_email: bool = False
    email: str = "alana@gmail.test"
    in_refresh: Callable[[], Awaitable[None]] | None = None
    seen: list[Seen] = field(default_factory=list[Seen])
    codes: dict[str, Grant] = field(default_factory=dict[str, Grant])
    refresh_tokens: dict[str, Grant] = field(default_factory=dict[str, Grant])
    access_tokens: dict[str, Grant] = field(default_factory=dict[str, Grant])
    paired: dict[str, str] = field(default_factory=dict[str, str])
    issued_access: list[str] = field(default_factory=list[str])
    issued_refresh: list[str] = field(default_factory=list[str])
    verifiers: list[str] = field(default_factory=list[str])
    counter: int = 0

    def mint_code(self, challenge: str, redirect_uri: str, scopes: tuple[str, ...], email: str | None = None) -> str:
        self.counter += 1
        code = f"code-{self.counter}-AUTHCODE"
        self.codes[code] = Grant(challenge, redirect_uri, scopes, email or self.email)
        return code

    def authorize(self, url: str) -> tuple[str, str]:
        """(code, state) for the authorization URL the app answered, as the consent screen would hand them back."""
        query = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
        assert urlsplit(url).netloc == "accounts.google.com", url
        assert query["client_id"] == CLIENT_ID and query["response_type"] == "code"
        asked = tuple(query["scope"].split())
        granted = asked if self.grant_scopes is None else self.grant_scopes
        return self.mint_code(query["code_challenge"], query["redirect_uri"], granted), query["state"]

    def calls(self, kind: str, grant: str | None = None) -> int:
        return sum(1 for s in self.seen if s.kind == kind and (grant is None or s.form.get("grant_type") == grant))

    def secret_values(self) -> set[str]:
        """Every secret this provider ever saw or issued: what no log, response or stored plaintext may carry."""
        return {CLIENT_SECRET, *self.codes, *self.access_tokens, *self.refresh_tokens, *self.issued_access,
                *self.issued_refresh, *self.verifiers}

    async def handle(self, request: httpx2.Request) -> httpx2.Response:
        host, path = request.url.host, request.url.path
        form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        auth = request.headers.get("authorization", "")
        bearer = auth[len("Bearer "):] if auth.startswith("Bearer ") else ""
        kind = "stray"
        if host.endswith(("google.com", "googleapis.com")):
            kind = "token" if path.endswith("/token") else "userinfo" if path.endswith("userinfo") else \
                "revoke" if path.endswith("revoke") else "stray"
        self.seen.append(Seen(kind, request.method, host, path, form, bearer))
        if kind == "token":
            return await self._token(request, form)
        if kind == "userinfo":
            return self._userinfo(bearer)
        return httpx2.Response(200 if kind == "revoke" else 404, json={})

    def _client_ok(self, request: httpx2.Request, form: dict[str, str]) -> bool:
        auth = request.headers.get("authorization", "")
        if auth.startswith("Basic "):
            return base64.b64decode(auth[6:]).decode() == f"{CLIENT_ID}:{CLIENT_SECRET}"
        return form.get("client_id") == CLIENT_ID and form.get("client_secret") == CLIENT_SECRET

    def _error(self, status: int, error: str) -> httpx2.Response:
        return httpx2.Response(status, json={"error": error, "error_description": "refused by the fake"})

    async def _token(self, request: httpx2.Request, form: dict[str, str]) -> httpx2.Response:
        if request.method != "POST":
            return self._error(405, "invalid_request")
        if not self._client_ok(request, form):
            return self._error(401, "invalid_client")
        if form.get("grant_type") == "authorization_code":
            return self._redeem(form)
        if form.get("grant_type") == "refresh_token":
            return await self._refresh(form)
        return self._error(400, "unsupported_grant_type")

    def _answer(self, grant: Grant, refresh: str | None, kept: str = "") -> httpx2.Response:
        self.counter += 1
        access = f"at-{self.counter}-ACCESSTOKEN"
        self.access_tokens[access] = grant
        self.issued_access.append(access)
        body: dict[str, Any] = {"access_token": access, "expires_in": self.expires_in, "token_type": "Bearer",
                                "scope": " ".join(grant.scopes)}
        if refresh is not None:
            body["refresh_token"] = refresh
            self.refresh_tokens[refresh] = grant
            self.issued_refresh.append(refresh)
        self.paired[access] = refresh or kept
        return httpx2.Response(200, content=json.dumps(body).encode(), headers={"content-type": "application/json"})

    def _redeem(self, form: dict[str, str]) -> httpx2.Response:
        verifier = form.get("code_verifier", "")
        self.verifiers.append(verifier)
        grant = self.codes.pop(form.get("code", ""), None)
        if grant is None or self.refuse_code:
            return self._error(400, "invalid_grant")
        if form.get("redirect_uri") != grant.redirect_uri or s256(verifier) != grant.challenge:
            return self._error(400, "invalid_grant")
        self.counter += 1
        refresh = None if self.omit_refresh else f"rt-{self.counter}-REFRESHTOKEN"
        return self._answer(grant, refresh)

    async def _refresh(self, form: dict[str, str]) -> httpx2.Response:
        if self.refresh_down:
            raise httpx2.ConnectError("the token endpoint is down")
        if self.refresh_status is not None:
            return self._error(self.refresh_status, "temporarily_unavailable")
        presented = form.get("refresh_token", "")
        grant = self.refresh_tokens.get(presented)
        if grant is None or self.refuse_refresh:
            return self._error(400, "invalid_grant")
        hook, self.in_refresh = self.in_refresh, None
        if hook is not None:
            await hook()
        if not self.rotate:
            return self._answer(grant, None, presented)
        if self.strict_rotation:
            self.refresh_tokens.pop(presented, None)
        self.counter += 1
        return self._answer(grant, f"rt-{self.counter}-REFRESHTOKEN")

    def _userinfo(self, bearer: str) -> httpx2.Response:
        grant = self.access_tokens.get(bearer)
        if grant is None or self.userinfo == "unauthorized":
            return self._error(401, "invalid_token")
        if self.userinfo == "down":
            return httpx2.Response(503, json={"error": "unavailable"})
        body: dict[str, object] = {"sub": "1100000000000000001"}
        if self.userinfo != "no_email" and ("email" in grant.scopes or self.always_email):
            body.update(email=grant.email, email_verified=True)
        return httpx2.Response(200, json=body)

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Every `httpx2.AsyncClient` of the process, however built, reaches this fake instead of the network."""
        transport = httpx2.MockTransport(self.handle)

        def transport_for(_: httpx2.AsyncClient, __: httpx2.URL) -> httpx2.AsyncBaseTransport:
            return transport

        monkeypatch.setattr(httpx2.AsyncClient, "_transport_for_url", transport_for)
