"""A fake provider, in process: its discovery document, its keys and its token endpoint behind an httpx2
MockTransport, so `OidcProvider` runs its real HTTP and JOSE code with no network. `authorize` plays the browser at
the provider's authorization endpoint: it reads the URL the app sent the browser to and hands back the code the provider
would put on the callback. The keys are made once, at import, since an RSA key costs about 0.1 s of CPU."""

import base64
import hashlib
import secrets
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx2
from joserfc import jwt
from joserfc.jwk import KeySet, OctKey, RSAKey

from ashley.signin.provider import OidcProvider, Client

ISSUER = "https://auth.test/application/o/ashley/"
CLIENT = Client(ISSUER, "ashley-client", "s3cret-client", "https://ashley.test/api/auth/callback")
KEY = RSAKey.generate_key(2048, parameters={"kid": "one"})
ROTATED = RSAKey.generate_key(2048, parameters={"kid": "two"})


@dataclass
class Grant:
    nonce: str
    challenge: str
    redirect_uri: str


@dataclass
class FakeIdp:
    """`sub` and `username` are who signs in next. `claims` overrides or adds ID-token claims (None drops one); `header` the JOSE
    header; `signer` the key, or an OctKey for an HS256 token. `token_status` other than 200 refuses the code."""

    sub: str = "a1b2c3hashedsub"
    username: str = "alana"
    claims: dict[str, Any] = field(default_factory=dict[str, Any])
    header: dict[str, Any] = field(default_factory=lambda: {"alg": "RS256", "kid": "one"})
    signer: RSAKey | OctKey = field(default_factory=lambda: KEY)
    published: list[RSAKey] = field(default_factory=lambda: [KEY])
    discovery_issuer: str = ISSUER
    token_status: int = 200
    grants: dict[str, Grant] = field(default_factory=dict[str, Grant])
    requests: list[httpx2.Request] = field(default_factory=list[httpx2.Request])

    def authorize(self, url: str) -> tuple[str, str]:
        """(code, state) for the authorization URL the app sent the browser to."""
        query = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
        assert query["code_challenge_method"] == "S256" and query["response_type"] == "code"
        assert query["client_id"] == CLIENT.client_id
        code = secrets.token_urlsafe(16)
        self.grants[code] = Grant(query["nonce"], query["code_challenge"], query["redirect_uri"])
        return code, query["state"]

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        path = request.url.path
        if path.endswith("/.well-known/openid-configuration"):
            return httpx2.Response(200, json={
                "issuer": self.discovery_issuer, "authorization_endpoint": "https://auth.test/application/o/authorize/",
                "token_endpoint": "https://auth.test/application/o/token/",
                "jwks_uri": "https://auth.test/application/o/ashley/jwks/"})
        if path.endswith("/jwks/"):
            return httpx2.Response(200, json=KeySet(list(self.published)).as_dict(private=False))
        if path.endswith("/token/"):
            return self._token(dict(parse_qs(request.content.decode())))
        return httpx2.Response(404)

    def _token(self, form: dict[str, list[str]]) -> httpx2.Response:
        one = {k: v[0] for k, v in form.items()}
        grant = self.grants.pop(one.get("code", ""), None)
        verifier = one.get("code_verifier", "")
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        if (self.token_status != 200 or grant is None or grant.challenge != challenge
                or one.get("client_secret") != CLIENT.client_secret or one.get("redirect_uri") != grant.redirect_uri):
            return httpx2.Response(self.token_status if self.token_status != 200 else 400,
                                   json={"error": "invalid_grant"})
        now = int(time.time())
        claims = {"iss": ISSUER, "aud": CLIENT.client_id, "sub": self.sub, "exp": now + 300, "iat": now,
                  "nonce": grant.nonce, "preferred_username": self.username, "email": "alana@example.test",
                  **self.claims}
        claims = {k: v for k, v in claims.items() if v is not None}
        algorithms = [self.header["alg"]]
        return httpx2.Response(200, json={"access_token": "at-" + secrets.token_urlsafe(8), "token_type": "Bearer",
                                          "id_token": jwt.encode(self.header, claims, self.signer, algorithms)})


def oidc_for(fake: FakeIdp, client: Client = CLIENT) -> OidcProvider:
    return OidcProvider(client, httpx2.AsyncClient(transport=httpx2.MockTransport(fake.handler)))
