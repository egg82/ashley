"""`OidcProvider` against the fake provider: a good code is the account it names, and every way an ID token can be
wrong (signature, algorithm, issuer, audience, expiry, nonce, subject) is SignInFailed, never an identity."""

import asyncio
import time
from typing import Any

import pytest
from joserfc.jwk import OctKey

from ashley.signin.model import Identity
from ashley.signin.oidc import OidcUnavailable, SignInFailed, pkce
from signin_support import ROTATED, FakeIdp, oidc_for


def sign_in(fake: FakeIdp, nonce: str = "n-123") -> Identity:
    async def run() -> Identity:
        oidc = oidc_for(fake)
        verifier, challenge = pkce()
        code, _ = fake.authorize(await oidc.authorize_url("st", nonce, challenge))
        return await oidc.identify(code, verifier, "n-123")
    return asyncio.run(run())


def test_a_good_code_is_the_account_it_names() -> None:
    assert sign_in(FakeIdp(sub="sub-9", username="sam")) == Identity("sub-9", "sam")


def test_a_token_without_preferred_username_names_the_account_by_its_name() -> None:
    assert sign_in(FakeIdp(sub="sub-9", claims={"preferred_username": None, "name": "sam"})) == Identity("sub-9", "sam")
    assert sign_in(FakeIdp(sub="sub-9", claims={"preferred_username": None})) == Identity("sub-9", "")


def test_the_preferred_username_wins_over_the_name() -> None:
    assert sign_in(FakeIdp(username="sam", claims={"name": "Samantha"})).username == "sam"


def test_the_authorization_url_asks_for_s256_pkce_and_the_registered_redirect() -> None:
    fake = FakeIdp()
    url = asyncio.run(oidc_for(fake).authorize_url("the-state", "the-nonce", "the-challenge"))
    assert url.startswith("https://auth.test/application/o/authorize/?")
    assert "code_challenge=the-challenge" in url and "code_challenge_method=S256" in url
    assert "state=the-state" in url and "nonce=the-nonce" in url
    assert "redirect_uri=https%3A%2F%2Fashley.test%2Fapi%2Fauth%2Fcallback" in url


@pytest.mark.parametrize("claims", [
    {"iss": "https://elsewhere.test/"},
    {"aud": "another-client"},
    {"aud": ["ashley-client", "another-client"]},
    {"exp": int(time.time()) - 3600},
    {"sub": ""},
    {"sub": 42},
    {"sub": None},
    {"exp": None},
    {"nonce": None},
])
def test_a_token_with_a_wrong_claim_is_refused(claims: dict[str, Any]) -> None:
    with pytest.raises(SignInFailed):
        sign_in(FakeIdp(claims=claims))


def test_a_token_for_another_sign_in_is_refused_by_its_nonce() -> None:
    with pytest.raises(SignInFailed):
        sign_in(FakeIdp(), nonce="someone-elses")


def test_a_token_signed_with_the_client_secret_is_refused() -> None:
    fake = FakeIdp(header={"alg": "HS256"}, signer=OctKey.import_key("s3cret-client"))
    with pytest.raises(SignInFailed):
        sign_in(fake)


def test_a_token_signed_by_a_key_provider_never_published_is_refused() -> None:
    with pytest.raises(SignInFailed):
        sign_in(FakeIdp(header={"alg": "RS256", "kid": "two"}, signer=ROTATED))


def test_a_rotated_key_is_fetched_again() -> None:
    fake = FakeIdp()

    async def run() -> Identity:
        oidc = oidc_for(fake)
        verifier, challenge = pkce()
        code, _ = fake.authorize(await oidc.authorize_url("s", "n", challenge))
        first = await oidc.identify(code, verifier, "n")
        fake.published, fake.header, fake.signer = [ROTATED], {"alg": "RS256", "kid": "two"}, ROTATED
        code, _ = fake.authorize(await oidc.authorize_url("s", "n", challenge))
        assert first.sub == fake.sub
        return await oidc.identify(code, verifier, "n")

    assert asyncio.run(run()).sub == fake.sub
    assert sum(r.url.path.endswith("/jwks/") for r in fake.requests) == 2


def test_a_wrong_verifier_is_refused_by_the_provider() -> None:
    fake = FakeIdp()

    async def run() -> Identity:
        oidc = oidc_for(fake)
        _, challenge = pkce()
        code, _ = fake.authorize(await oidc.authorize_url("s", "n", challenge))
        return await oidc.identify(code, pkce()[0], "n")

    with pytest.raises(SignInFailed):
        asyncio.run(run())


def test_a_discovery_document_naming_another_issuer_is_unavailable() -> None:
    with pytest.raises(OidcUnavailable):
        asyncio.run(oidc_for(FakeIdp(discovery_issuer="https://evil.test/")).authorize_url("s", "n", "c"))


def test_a_refused_code_is_sign_in_failed() -> None:
    with pytest.raises(SignInFailed):
        sign_in(FakeIdp(token_status=400))
