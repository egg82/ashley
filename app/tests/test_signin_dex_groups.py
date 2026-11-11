"""`ADMIN_GROUP` against a real Dex, whose static user is in two groups (`tests/dex/config.yaml`): with an admin group
configured the sign-in asks for the `groups` scope and the ID token's `groups` claim says whether the account is in it;
with none, the scope is not asked for and nothing is said."""

import asyncio
from urllib.parse import parse_qs, urlsplit

import httpx2
import pytest
from ashley.signin.model import Identity
from ashley.signin.oidc import pkce
from ashley.signin.provider import Client, OidcProvider
from signin_dex_support import REDIRECT_URI, dex_issuer, log_in

XFAIL = pytest.mark.xfail(strict=True, reason="the admin role is not implemented yet")


def sign_in(admin_group: str) -> tuple[Identity, list[str]]:
    """Who signed in, and the scopes the authorization request asked for."""
    async def run() -> tuple[Identity, list[str]]:
        async with httpx2.AsyncClient() as http:
            oidc = OidcProvider(Client(dex_issuer(), "ashley-test", "ashley-test-secret", REDIRECT_URI, admin_group),
                                http)
            verifier, challenge = pkce()
            url = await oidc.authorize_url("the-state", "n-1", challenge)
            code, _ = log_in(url)
            return await oidc.identify(code, verifier, "n-1"), parse_qs(urlsplit(url).query)["scope"][0].split()
    return asyncio.run(run())


@XFAIL
def test_a_member_of_the_admin_group_is_said_to_be_one() -> None:
    identity, scopes = sign_in("ashley-test-admins")
    assert identity.admin_group is True and "groups" in scopes


@XFAIL
def test_an_account_outside_the_admin_group_is_said_not_to_be() -> None:
    identity, scopes = sign_in("some-other-group")
    assert identity.admin_group is False and "groups" in scopes


def test_with_no_admin_group_the_scope_is_not_asked_for_and_nothing_is_said() -> None:
    identity, scopes = sign_in("")
    assert identity.admin_group is None and "groups" not in scopes and identity.sub
