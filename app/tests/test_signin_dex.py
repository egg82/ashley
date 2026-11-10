"""`OidcProvider` against a real Dex (its static client and password user), through Dex's own login form: the account
it names is who signed in, and a wrong client secret or a token for another nonce is SignInFailed."""

import asyncio

import httpx2
import pytest

from ashley.signin.model import Identity
from ashley.signin.oidc import SignInFailed, pkce
from ashley.signin.provider import Client, OidcProvider
from signin_dex_support import USERNAME, dex_client, dex_issuer, log_in


def sign_in(client: Client, nonce: str = "n-1", identify_nonce: str = "n-1") -> Identity:
    async def run() -> Identity:
        async with httpx2.AsyncClient() as http:
            oidc = OidcProvider(client, http)
            verifier, challenge = pkce()
            code, state = log_in(await oidc.authorize_url("the-state", nonce, challenge))
            assert state == "the-state"
            return await oidc.identify(code, verifier, identify_nonce)
    return asyncio.run(run())


def test_the_static_user_signs_in_as_an_account_with_a_sub() -> None:
    assert sign_in(dex_client(dex_issuer())).sub


@pytest.mark.xfail(strict=True, reason="Dex's static passwords carry the username as `name`, with no `preferred_username`")
def test_the_account_carries_the_username_dex_names() -> None:
    assert sign_in(dex_client(dex_issuer())).username == USERNAME


def test_the_same_user_is_the_same_sub_each_time() -> None:
    client = dex_client(dex_issuer())
    assert sign_in(client).sub == sign_in(client).sub


def test_a_wrong_client_secret_is_refused() -> None:
    with pytest.raises(SignInFailed):
        sign_in(dex_client(dex_issuer(), secret="not-the-secret"))


def test_a_token_for_another_nonce_is_refused() -> None:
    with pytest.raises(SignInFailed):
        sign_in(dex_client(dex_issuer()), nonce="n-1", identify_nonce="someone-elses")
