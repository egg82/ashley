"""Google's OAuth endpoints and userinfo behind `httpx2.MockTransport`, so the real `GoogleOAuth` runs against them: the
consent URL is read as the browser would, a code is redeemed only with the verifier whose S256 challenge it was issued
for, a refresh token is accepted until revoked, and userinfo answers only for an access token this fake issued."""

import base64
import hashlib
import secrets
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlsplit

import httpx2
from ashley.google.oauth import App, GoogleOAuth

REDIRECT = "https://ashley.test/api/connections/oauth/google/callback"
EMAIL = "alana@gmail.test"
SCOPES = "openid https://www.googleapis.com/auth/userinfo.email https://www.googleapis.com/auth/gmail.modify"


def s256(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


@dataclass
class FakeGoogle:
    """`granted` is the scope string the token answer reports; `rotate` makes a refresh answer a new refresh token too;
    `down` makes every endpoint answer 503; `refuse_userinfo` makes userinfo turn any token away; `expires_in` is what each token answer says."""

    granted: str = SCOPES
    rotate: bool = False
    down: bool = False
    refuse_userinfo: bool = False
    expires_in: int = 3600
    codes: dict[str, str] = field(default_factory=dict[str, str])
    refresh_tokens: set[str] = field(default_factory=set[str])
    access_tokens: set[str] = field(default_factory=set[str])
    seen: list[tuple[str, str]] = field(default_factory=list[tuple[str, str]])

    def provider(self) -> GoogleOAuth:
        http = httpx2.AsyncClient(transport=httpx2.MockTransport(self.handle))
        return GoogleOAuth(App("client-id", "client-secret", REDIRECT), http)

    def authorize(self, url: str) -> tuple[str, str]:
        """(code, state) for the consent URL the app answered."""
        query = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
        assert query["access_type"] == "offline" and query["code_challenge_method"] == "S256"
        assert query["redirect_uri"] == REDIRECT and query["client_id"] == "client-id"
        code = secrets.token_urlsafe(16)
        self.codes[code] = query["code_challenge"]
        return code, query["state"]

    def calls(self, grant: str) -> int:
        return sum(1 for g, _ in self.seen if g == grant)

    def _issue(self, with_refresh: bool) -> dict[str, object]:
        access = f"ya29.{secrets.token_urlsafe(12)}"
        self.access_tokens.add(access)
        body: dict[str, object] = {"access_token": access, "expires_in": self.expires_in, "token_type": "Bearer",
                                   "scope": self.granted}
        if with_refresh:
            refresh = f"1//{secrets.token_urlsafe(12)}"
            self.refresh_tokens.add(refresh)
            body["refresh_token"] = refresh
        return body

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        if self.down:
            return httpx2.Response(503)
        if request.url.path == "/v1/userinfo":
            token = request.headers.get("authorization", "").removeprefix("Bearer ")
            self.seen.append(("userinfo", token))
            if self.refuse_userinfo or token not in self.access_tokens:
                return httpx2.Response(401, json={"error": "invalid_token"})
            return httpx2.Response(200, json={"sub": "1", "email": EMAIL})
        form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        self.seen.append((form["grant_type"], form.get("code", form.get("refresh_token", ""))))
        assert form["client_id"] == "client-id" and form["client_secret"] == "client-secret"
        if form["grant_type"] == "authorization_code":
            challenge = self.codes.pop(form["code"], "")
            if not challenge or challenge != s256(form["code_verifier"]):
                return httpx2.Response(400, json={"error": "invalid_grant"})
            return httpx2.Response(200, json=self._issue(True))
        if form["refresh_token"] not in self.refresh_tokens:
            return httpx2.Response(400, json={"error": "invalid_grant", "error_description": "revoked"})
        body = self._issue(self.rotate)
        body.pop("scope")
        if self.rotate:
            self.refresh_tokens.discard(form["refresh_token"])
        return httpx2.Response(200, json=body)
