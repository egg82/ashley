"""The fake Google keeps to what Google documents, so a green suite means the code met a provider that can say no: each
case here is one way the fake refuses, driven through its HTTP boundary with no app and no database."""

import asyncio
from collections.abc import Coroutine
from typing import Any, TypeVar

import httpx2
import pytest
from mail_oauth_blind_fake_support import CLIENT_ID, CLIENT_SECRET, FakeGoogle, carries, holds_verifier, s256

REDIRECT = "https://ashley.test/api/connections/oauth/google/callback"
TOKEN = "https://oauth2.googleapis.com/token"
AUTH = (CLIENT_ID, CLIENT_SECRET)
T = TypeVar("T")


def go(scenario: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(scenario)


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeGoogle:
    google = FakeGoogle()
    google.install(monkeypatch)
    return google


async def redeem(fake: FakeGoogle, code: str, verifier: str, auth: tuple[str, str] = AUTH) -> httpx2.Response:
    async with httpx2.AsyncClient() as http:
        return await http.post(TOKEN, data={"grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT,
                                            "code_verifier": verifier}, auth=auth)


async def refresh(token: str) -> httpx2.Response:
    async with httpx2.AsyncClient() as http:
        return await http.post(TOKEN, data={"grant_type": "refresh_token", "refresh_token": token}, auth=AUTH)


def test_a_code_redeems_once_with_its_verifier(fake: FakeGoogle) -> None:
    async def scenario() -> None:
        code = fake.mint_code(s256("v" * 43), REDIRECT, ("openid", "email"))
        assert (await redeem(fake, code, "w" * 43)).status_code == 400
        code = fake.mint_code(s256("v" * 43), REDIRECT, ("openid", "email"))
        ok = await redeem(fake, code, "v" * 43)
        assert ok.status_code == 200 and ok.json()["scope"] == "openid email" and ok.json()["refresh_token"]
        assert (await redeem(fake, code, "v" * 43)).status_code == 400

    go(scenario())


def test_the_client_is_authenticated(fake: FakeGoogle) -> None:
    async def scenario() -> None:
        code = fake.mint_code(s256("v" * 43), REDIRECT, ("openid",))
        assert (await redeem(fake, code, "v" * 43, ("someone", "else"))).status_code == 401

    go(scenario())


def test_a_refresh_token_never_issued_is_refused_and_a_rotated_one_only_when_strict(fake: FakeGoogle) -> None:
    async def scenario() -> None:
        code = fake.mint_code(s256("v" * 43), REDIRECT, ("openid",))
        first = (await redeem(fake, code, "v" * 43)).json()["refresh_token"]
        assert (await refresh("forged")).status_code == 400
        fake.rotate = fake.strict_rotation = True
        second = (await refresh(first)).json()["refresh_token"]
        assert second != first and (await refresh(first)).status_code == 400 and (await refresh(second)).status_code == 200

    go(scenario())


def test_userinfo_answers_only_for_an_issued_access_token(fake: FakeGoogle) -> None:
    async def scenario() -> None:
        code = fake.mint_code(s256("v" * 43), REDIRECT, ("openid", "email"))
        access = (await redeem(fake, code, "v" * 43)).json()["access_token"]
        async with httpx2.AsyncClient() as http:
            url = "https://openidconnect.googleapis.com/v1/userinfo"
            assert (await http.get(url, headers={"authorization": "Bearer nope"})).status_code == 401
            got = await http.get(url, headers={"authorization": f"Bearer {access}"})
        assert got.json()["email"] == fake.email
        assert fake.calls("userinfo") == 2 and fake.calls("token") == 1

    go(scenario())


def test_a_host_that_is_not_googles_is_a_stray(fake: FakeGoogle) -> None:
    async def scenario() -> None:
        async with httpx2.AsyncClient() as http:
            assert (await http.get("https://evil.test/token")).status_code == 404
        assert fake.calls("stray") == 1

    go(scenario())


def test_the_text_probes_can_find_what_they_look_for() -> None:
    verifier = "v" * 43
    assert holds_verifier(f"(\\x01, 1, {verifier}, now)", s256(verifier))
    assert holds_verifier(f"(\\x01, 1, \\x{verifier.encode().hex()})", s256(verifier))
    assert not holds_verifier("(\\x01, 1, nothing here)", s256(verifier))
    assert carries("abc \\x" + b"token".hex(), "token") and not carries("abc", "token")
