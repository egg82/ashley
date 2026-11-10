"""Discord's OAuth2 over HTTP (https://docs.discord.com/developers/topics/oauth2): the code is redeemed at the token
endpoint, the access token read once at `GET /users/@me` and then revoked, so Ashley does not stay in the person's
authorized apps. A revoke that fails is logged and does not fail the link."""

import logging
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx2
from pydantic import TypeAdapter

from .. import logs
from .discord import DiscordOAuth, DiscordUser, LinkFailed, LinkUnavailable

AUTHORIZE_URL = "https://discord.com/oauth2/authorize"
TOKEN_URL = "https://discord.com/api/oauth2/token"
REVOKE_URL = "https://discord.com/api/oauth2/token/revoke"
ME_URL = "https://discord.com/api/v10/users/@me"
SCOPE = "identify"
_OBJECT = TypeAdapter(dict[str, Any])
log = logging.getLogger("ashley.signin")


@dataclass(frozen=True)
class App:
    """The Discord application people link through: its OAuth2 client, and `redirect_uri` exactly as registered on
    it, since Discord matches it exactly."""

    client_id: str
    client_secret: str
    redirect_uri: str


class HttpDiscordOAuth(DiscordOAuth):
    def __init__(self, app: App, http: httpx2.AsyncClient) -> None:
        self.app = app
        self._http = http

    def configured(self) -> bool:
        return True

    async def authorize_url(self, state: str, challenge: str) -> str:
        query = {"response_type": "code", "client_id": self.app.client_id, "redirect_uri": self.app.redirect_uri,
                 "scope": SCOPE, "state": state, "code_challenge": challenge,
                 "code_challenge_method": "S256"}
        return f"{AUTHORIZE_URL}?{urlencode(query)}"

    async def identify(self, code: str, verifier: str) -> DiscordUser:
        tokens = await self._token(code, verifier)
        access = tokens.get("access_token")
        if not isinstance(access, str) or not access:
            raise LinkFailed("no access token in the token answer")
        try:
            return _user(await self._me(access))
        finally:
            await self._revoke(access)

    async def _token(self, code: str, verifier: str) -> dict[str, Any]:
        form = {"grant_type": "authorization_code", "code": code, "redirect_uri": self.app.redirect_uri,
                "code_verifier": verifier}
        try:
            response = await self._http.post(TOKEN_URL, data=form, auth=(self.app.client_id, self.app.client_secret),
                                             headers={"accept": "application/json"})
        except httpx2.HTTPError as e:
            raise LinkUnavailable(f"token endpoint unreachable: {type(e).__name__}") from None
        if response.status_code >= 500:
            raise LinkUnavailable(f"token endpoint answered {response.status_code}")
        if response.status_code != 200:
            raise LinkFailed(f"token endpoint answered {response.status_code}")
        return _object(response, "token endpoint")

    async def _revoke(self, access: str) -> None:
        try:
            response = await self._http.post(REVOKE_URL, data={"token": access, "token_type_hint": "access_token"},
                                             auth=(self.app.client_id, self.app.client_secret))
        except httpx2.HTTPError as e:
            logs.warning(log, "discord.revoke_failed", reason=type(e).__name__)
            return
        if response.status_code != 200:
            logs.warning(log, "discord.revoke_failed", status=response.status_code)

    async def _me(self, access: str) -> dict[str, Any]:
        try:
            response = await self._http.get(ME_URL, headers={"authorization": f"Bearer {access}",
                                                             "accept": "application/json"})
        except httpx2.HTTPError as e:
            raise LinkUnavailable(f"users/@me unreachable: {type(e).__name__}") from None
        if response.status_code >= 500:
            raise LinkUnavailable(f"users/@me answered {response.status_code}")
        if response.status_code != 200:
            raise LinkFailed(f"users/@me answered {response.status_code}")
        return _object(response, "users/@me")


def _object(response: httpx2.Response, where: str) -> dict[str, Any]:
    try:
        return _OBJECT.validate_python(response.json())
    except ValueError:
        raise LinkFailed(f"{where} answered something other than a JSON object") from None


def _user(me: dict[str, Any]) -> DiscordUser:
    """The user `/users/@me` names. Its `id` must be a snowflake, digits only."""
    user_id, username, discriminator = me.get("id"), me.get("username"), me.get("discriminator")
    if not isinstance(user_id, str) or not user_id.isascii() or not user_id.isdigit():
        raise LinkFailed("users/@me named no user id")
    handle = username if isinstance(username, str) else ""
    if handle and isinstance(discriminator, str) and discriminator not in ("", "0"):
        handle = f"{handle}#{discriminator}"
    return DiscordUser(user_id, handle)
