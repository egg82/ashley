"""`HttpDiscordOAuth` against a fake Discord behind an httpx2 MockTransport: the authorization URL asks for `identify`
alone with S256 PKCE and the registered redirect; the code is redeemed with the client's Basic credentials, the
verifier and that redirect, as a form; `/users/@me` is read with the access token; refusals and outages are told
apart. The settings that wire it come as a pair, with `PUBLIC_URL`."""

import asyncio
import base64
from collections.abc import Callable, Mapping
from urllib.parse import parse_qs, urlsplit

import httpx2
import pytest
from ashley import logs
from ashley.settings import Settings, from_env
from ashley.signin.discord import DiscordUser, LinkFailed, LinkUnavailable
from ashley.signin.discord_http import App, HttpDiscordOAuth

APP = App("1234", "zqSECRET", "https://ashley.test/api/accounts/discord/callback")
Handler = Callable[[httpx2.Request], httpx2.Response]


def discord(me: Mapping[str, object] | None = None, token_status: int = 200, me_status: int = 200,
            seen: list[httpx2.Request] | None = None, revoke_status: int = 200) -> Handler:
    def handle(request: httpx2.Request) -> httpx2.Response:
        if seen is not None:
            seen.append(request)
        if request.url.path == "/api/oauth2/token":
            return httpx2.Response(token_status, json={"access_token": "zqACCESS", "token_type": "Bearer"})
        if request.url.path == "/api/v10/users/@me":
            if request.headers.get("authorization") != "Bearer zqACCESS":
                return httpx2.Response(401)
            return httpx2.Response(me_status, json=me if me is not None else {"id": "80351110224678912",
                                                                              "username": "nelly", "discriminator": "0"})
        if request.url.path == "/api/oauth2/token/revoke":
            return httpx2.Response(revoke_status, json={})
        return httpx2.Response(404)
    return handle


def oauth(handler: Handler) -> HttpDiscordOAuth:
    return HttpDiscordOAuth(APP, httpx2.AsyncClient(transport=httpx2.MockTransport(handler)))


def test_the_authorization_url_asks_for_identify_with_pkce() -> None:
    url = asyncio.run(oauth(discord()).authorize_url("st", "ch"))
    parts = urlsplit(url)
    query = {k: v[0] for k, v in parse_qs(parts.query).items()}
    assert (parts.scheme, parts.netloc, parts.path) == ("https", "discord.com", "/oauth2/authorize")
    assert query == {"response_type": "code", "client_id": "1234", "redirect_uri": APP.redirect_uri,
                     "scope": "identify", "state": "st", "code_challenge": "ch", "code_challenge_method": "S256"}


def test_a_code_is_redeemed_and_the_user_read() -> None:
    seen: list[httpx2.Request] = []
    user = asyncio.run(oauth(discord(seen=seen)).identify("cd", "vf"))
    assert user == DiscordUser("80351110224678912", "nelly")
    token = seen[0]
    form = {k: v[0] for k, v in parse_qs(token.content.decode()).items()}
    assert form == {"grant_type": "authorization_code", "code": "cd", "redirect_uri": APP.redirect_uri,
                    "code_verifier": "vf"}
    assert token.headers["authorization"] == "Basic " + base64.b64encode(b"1234:zqSECRET").decode()
    assert token.headers["content-type"] == "application/x-www-form-urlencoded"


def test_the_access_token_is_revoked_after_the_user_is_read() -> None:
    seen: list[httpx2.Request] = []
    asyncio.run(oauth(discord(seen=seen)).identify("cd", "vf"))
    assert [r.url.path for r in seen] == ["/api/oauth2/token", "/api/v10/users/@me", "/api/oauth2/token/revoke"]
    revoke = seen[2]
    form = {k: v[0] for k, v in parse_qs(revoke.content.decode()).items()}
    assert form == {"token": "zqACCESS", "token_type_hint": "access_token"}
    assert revoke.headers["authorization"] == "Basic " + base64.b64encode(b"1234:zqSECRET").decode()


def test_the_token_is_revoked_even_when_the_user_cannot_be_read() -> None:
    seen: list[httpx2.Request] = []
    with pytest.raises(LinkFailed):
        asyncio.run(oauth(discord(me_status=401, seen=seen)).identify("cd", "vf"))
    assert seen[-1].url.path == "/api/oauth2/token/revoke"


def test_a_revoke_that_fails_does_not_fail_the_link(capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup({})
    user = asyncio.run(oauth(discord(revoke_status=500)).identify("cd", "vf"))
    assert user == DiscordUser("80351110224678912", "nelly")
    out = capsys.readouterr().out
    assert "event=discord.revoke_failed" in out and "status=500" in out and "zqACCESS" not in out


def test_an_unreachable_revoke_does_not_fail_the_link(capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup({})
    ok = discord()

    def handle(request: httpx2.Request) -> httpx2.Response:
        if request.url.path.endswith("/revoke"):
            raise httpx2.ConnectError("no route", request=request)
        return ok(request)
    assert asyncio.run(oauth(handle).identify("cd", "vf")).id == "80351110224678912"
    assert "reason=ConnectError" in capsys.readouterr().out


def test_a_legacy_discriminator_is_part_of_the_handle() -> None:
    me = {"id": "42", "username": "nelly", "discriminator": "0042"}
    assert asyncio.run(oauth(discord(me)).identify("cd", "vf")).handle == "nelly#0042"


@pytest.mark.parametrize(("handler", "error"), [
    (discord(token_status=400), LinkFailed), (discord(token_status=502), LinkUnavailable),
    (discord(me_status=401), LinkFailed), (discord(me_status=503), LinkUnavailable),
    (discord({"id": "not-a-snowflake", "username": "x"}), LinkFailed), (discord({"username": "x"}), LinkFailed)])
def test_refusals_and_outages_are_told_apart(handler: Handler, error: type[Exception]) -> None:
    with pytest.raises(error) as raised:
        asyncio.run(oauth(handler).identify("cd", "vf"))
    assert "zqACCESS" not in str(raised.value) and "zqSECRET" not in str(raised.value)


def test_unreachable_discord_is_unavailable() -> None:
    def down(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("no route", request=request)
    with pytest.raises(LinkUnavailable):
        asyncio.run(oauth(down).identify("cd", "vf"))


@pytest.mark.parametrize("env", [{"DISCORD_OAUTH_CLIENT_ID": "1"}, {"DISCORD_OAUTH_CLIENT_SECRET": "s"},
                                 {"DISCORD_OAUTH_CLIENT_ID": "1", "DISCORD_OAUTH_CLIENT_SECRET": "s"}])
def test_the_settings_come_as_a_pair_with_public_url(env: dict[str, str]) -> None:
    with pytest.raises(ValueError):
        from_env({"DATABASE_URL": "x", **env})
    both = {"DATABASE_URL": "x", "DISCORD_OAUTH_CLIENT_ID": "1", "DISCORD_OAUTH_CLIENT_SECRET": "s",
            "PUBLIC_URL": "https://ashley.test/"}
    assert from_env(both) == Settings(database_url="x", build_version="dev", discord_oauth_client_id="1",
                                      discord_oauth_client_secret="s", public_url="https://ashley.test")
    assert from_env({"DATABASE_URL": "x"}).discord_oauth_client_id == ""
