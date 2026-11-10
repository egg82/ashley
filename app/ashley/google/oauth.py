"""Google's OAuth2 over HTTP (https://developers.google.com/identity/protocols/oauth2/web-server): authorization code
with PKCE and offline access, so the code is worth a refresh token. Google's userinfo is the one authenticated read
that proves an access token reaches an account."""

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx2
from pydantic import TypeAdapter

from ..connections.kinds import Refusal
from ..connections.model import Grant
from ..connections.oauth import OAuthFailed, OAuthProvider, OAuthRefused, OAuthUnavailable

NAME = "google"
AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
_OBJECT = TypeAdapter(dict[str, Any])


@dataclass(frozen=True)
class App:
    """The Google OAuth client people connect through, and `redirect_uri` exactly as registered on it."""

    client_id: str
    client_secret: str
    redirect_uri: str


def _object(response: httpx2.Response) -> dict[str, Any] | None:
    try:
        return _OBJECT.validate_python(response.json())
    except ValueError:
        return None


def _grant(body: dict[str, Any]) -> Grant | None:
    access, refresh, expires, scope = (body.get(k) for k in ("access_token", "refresh_token", "expires_in", "scope"))
    if not isinstance(access, str) or not access or isinstance(expires, bool) or not isinstance(expires, int | float):
        return None
    if refresh is not None and (not isinstance(refresh, str) or not refresh):
        return None
    return Grant(access, refresh, int(expires), tuple(scope.split()) if isinstance(scope, str) else ())


class GoogleOAuth(OAuthProvider):
    def __init__(self, app: App, http: httpx2.AsyncClient) -> None:
        self.app = app
        self._http = http

    def authorize_url(self, state: str, challenge: str, scopes: tuple[str, ...]) -> str:
        query = {"response_type": "code", "client_id": self.app.client_id, "redirect_uri": self.app.redirect_uri,
                 "scope": " ".join(scopes), "state": state, "code_challenge": challenge,
                 "code_challenge_method": "S256", "access_type": "offline", "prompt": "consent"}
        return f"{AUTHORIZE_URL}?{urlencode(query)}"

    async def redeem(self, code: str, verifier: str) -> Grant:
        response = await self._token({"grant_type": "authorization_code", "code": code,
                                      "redirect_uri": self.app.redirect_uri, "code_verifier": verifier})
        if response.status_code >= 500:
            raise OAuthUnavailable(f"token endpoint answered {response.status_code}")
        body = _object(response)
        if response.status_code != 200 or body is None:
            raise OAuthFailed(f"token endpoint answered {response.status_code}")
        grant = _grant(body)
        if grant is None or grant.refresh_token is None:
            raise OAuthFailed("the token answer has no access token and refresh token")
        return grant

    async def refresh(self, refresh_token: str) -> Grant:
        response = await self._token({"grant_type": "refresh_token", "refresh_token": refresh_token})
        body = _object(response)
        if response.status_code == 400 and body is not None and body.get("error") == "invalid_grant":
            raise OAuthRefused("invalid_grant")
        grant = _grant(body) if response.status_code == 200 and body is not None else None
        if grant is None:
            raise OAuthUnavailable(f"token endpoint answered {response.status_code}")
        return grant

    async def check(self, access_token: str) -> Refusal | None:
        try:
            response = await self._http.get(USERINFO_URL, headers={"authorization": f"Bearer {access_token}",
                                                                   "accept": "application/json"})
        except httpx2.HTTPError:
            return "unreachable"
        if response.status_code in (401, 403):
            return "key_refused"
        if response.status_code >= 500:
            return "unreachable"
        body = _object(response) if response.status_code == 200 else None
        email = None if body is None else body.get("email")
        return None if isinstance(email, str) and email else "wrong_service"

    async def _token(self, form: dict[str, str]) -> httpx2.Response:
        form = {**form, "client_id": self.app.client_id, "client_secret": self.app.client_secret}
        try:
            return await self._http.post(TOKEN_URL, data=form, headers={"accept": "application/json"})
        except httpx2.HTTPError as e:
            raise OAuthUnavailable(f"token endpoint unreachable: {type(e).__name__}") from None
