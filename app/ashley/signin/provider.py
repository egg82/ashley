"""Any OIDC provider: its discovery document and signing keys, fetched on first use and kept for the
life of the pod (a cache, not state: any pod fetches its own), the keys again when a token names one not seen,
which is the provider rotating its key. The only module that imports joserfc."""

import asyncio
import logging
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx2
from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import KeySet, KeySetSerialization
from pydantic import TypeAdapter

from .. import logs
from .model import Identity
from .oidc import Oidc, OidcUnavailable, SignInFailed

log = logging.getLogger("ashley.signin")

ALGORITHMS = ["RS256", "RS384", "RS512", "ES256", "ES384"]   # signed by the provider's key; never HS* or none
SCOPE = "openid profile email"
LEEWAY_S = 60
_OBJECT = TypeAdapter(dict[str, Any])
_KEY_SET = TypeAdapter(KeySetSerialization)


@dataclass(frozen=True)
class Client:
    """The confidential client the provider knows: `issuer` as its discovery document names it (a trailing slash is
    ignored), and `redirect_uri` exactly as registered there, since the provider matches it strictly."""

    issuer: str
    client_id: str
    client_secret: str
    redirect_uri: str


def _username(claims: dict[str, Any]) -> str:
    """`preferred_username`, else `name`: Dex's password users carry only the latter."""
    for claim in ("preferred_username", "name"):
        value = claims.get(claim)
        if isinstance(value, str) and value:
            return value
    return ""


class OidcProvider(Oidc):
    """`client` is the confidential client it signs in as."""

    def __init__(self, client: Client, http: httpx2.AsyncClient) -> None:
        self.client = client
        self._http = http
        self._meta: dict[str, Any] | None = None
        self._keys: KeySet | None = None
        self._lock = asyncio.Lock()

    async def authorize_url(self, state: str, nonce: str, challenge: str) -> str:
        meta = await self._discovery()
        query = {"response_type": "code", "client_id": self.client.client_id,
                 "redirect_uri": self.client.redirect_uri, "scope": SCOPE, "state": state, "nonce": nonce,
                 "code_challenge": challenge, "code_challenge_method": "S256"}
        return f"{meta['authorization_endpoint']}?{urlencode(query)}"

    async def identify(self, code: str, verifier: str, nonce: str) -> Identity:
        meta = await self._discovery()
        tokens = await self._post(meta["token_endpoint"], {
            "grant_type": "authorization_code", "code": code, "redirect_uri": self.client.redirect_uri,
            "client_id": self.client.client_id, "client_secret": self.client.client_secret,
            "code_verifier": verifier})
        id_token = tokens.get("id_token")
        if not isinstance(id_token, str):
            raise SignInFailed("no id_token in the token answer")
        claims = await self._verify(id_token, meta["issuer"], nonce)
        return Identity(claims["sub"], _username(claims))

    async def _discovery(self) -> dict[str, Any]:
        async with self._lock:
            if self._meta is None:
                meta = await self._get(self.client.issuer.rstrip("/") + "/.well-known/openid-configuration")
                if str(meta.get("issuer", "")).rstrip("/") != self.client.issuer.rstrip("/"):
                    raise OidcUnavailable("the discovery document names another issuer")
                if not all(isinstance(meta.get(k), str) for k in ("authorization_endpoint", "token_endpoint", "jwks_uri")):
                    raise OidcUnavailable("the discovery document lacks an endpoint")
                self._meta = meta
            return self._meta

    async def _key_set(self, fresh: bool) -> KeySet:
        async with self._lock:
            if self._keys is None or fresh:
                assert self._meta is not None
                try:
                    self._keys = KeySet.import_key_set(_KEY_SET.validate_python(await self._get(self._meta["jwks_uri"])))
                except (ValueError, KeyError, JoseError) as e:
                    raise OidcUnavailable("the provider's keys could not be read") from e
            return self._keys

    async def _verify(self, id_token: str, issuer: str, nonce: str) -> dict[str, Any]:
        try:
            try:
                token = jwt.decode(id_token, await self._key_set(fresh=False), algorithms=ALGORITHMS)
            except (ValueError, KeyError, JoseError) as e:
                logs.info(log, "signin.keys_refetch", reason=type(e).__name__)
                token = jwt.decode(id_token, await self._key_set(fresh=True), algorithms=ALGORITHMS)
            jwt.JWTClaimsRegistry(
                leeway=LEEWAY_S, iss={"essential": True, "value": issuer},
                aud={"essential": True, "value": self.client.client_id}, sub={"essential": True},
                exp={"essential": True}, nonce={"essential": True, "value": nonce},
            ).validate(token.claims)
        except (ValueError, KeyError, JoseError) as e:
            raise SignInFailed(f"id token refused: {type(e).__name__}") from None
        claims = dict(token.claims)
        audience = claims["aud"]
        if not isinstance(audience, str) and audience != [self.client.client_id] \
                and claims.get("azp") != self.client.client_id:
            raise SignInFailed("id token is for several audiences and not authorized for this one")
        return claims

    async def _get(self, url: str) -> dict[str, Any]:
        try:
            response = await self._http.get(url)
            response.raise_for_status()
            return _OBJECT.validate_python(response.json())
        except (httpx2.HTTPError, ValueError) as e:
            raise OidcUnavailable(f"provider answered badly: {type(e).__name__}") from None

    async def _post(self, url: str, form: dict[str, str]) -> dict[str, Any]:
        try:
            response = await self._http.post(url, data=form, headers={"accept": "application/json"})
        except httpx2.HTTPError as e:
            raise OidcUnavailable(f"token endpoint unreachable: {type(e).__name__}") from None
        if response.status_code != 200:
            raise SignInFailed(f"token endpoint answered {response.status_code}")
        try:
            return _OBJECT.validate_python(response.json())
        except ValueError:
            raise SignInFailed("token endpoint answered something other than a JSON object") from None

