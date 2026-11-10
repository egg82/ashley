"""Google's OAuth adapter against its endpoints faked at the HTTP boundary: the consent URL asks for offline access and
PKCE; a code is worth a grant with a refresh token or nothing; a refresh token Google calls `invalid_grant` is refused and
any other failure is unavailable; userinfo's answers map to the check's refusals; the settings come as a pair."""

import asyncio
from urllib.parse import parse_qs, urlsplit

import httpx2
import pytest
from ashley.connections.oauth import OAuthFailed, OAuthRefused, OAuthUnavailable
from ashley.settings import Settings, from_env
from ashley.google.oauth import App, GoogleOAuth
from oauth_google_support import REDIRECT, SCOPES, FakeGoogle, s256


def test_the_consent_url_asks_for_offline_access_with_pkce_and_the_kinds_scopes() -> None:
    url = FakeGoogle().provider().authorize_url("st", s256("v"), ("openid", "email"))
    query = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
    assert urlsplit(url).netloc == "accounts.google.com"
    assert (query["scope"], query["state"], query["code_challenge"], query["access_type"], query["prompt"]) == (
        "openid email", "st", s256("v"), "offline", "consent")


def test_a_code_is_worth_a_grant_with_a_refresh_token_and_the_scopes_google_says() -> None:
    google = FakeGoogle()
    code = "c1"
    google.codes[code] = s256("verifier")
    grant = asyncio.run(google.provider().redeem(code, "verifier"))
    assert grant.refresh_token in google.refresh_tokens and grant.expires_in_s == 3600
    assert grant.scopes == tuple(SCOPES.split())
    assert "refresh_token" not in repr(grant) and grant.access_token not in repr(grant)


def test_a_code_with_the_wrong_verifier_is_failed_and_an_answer_with_no_refresh_token_is_failed() -> None:
    google = FakeGoogle()
    google.codes["c"] = s256("right")
    with pytest.raises(OAuthFailed):
        asyncio.run(google.provider().redeem("c", "wrong"))

    def no_refresh(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json={"access_token": "a", "expires_in": 3600})
    provider = GoogleOAuth(App("id", "secret", REDIRECT), httpx2.AsyncClient(transport=httpx2.MockTransport(no_refresh)))
    with pytest.raises(OAuthFailed):
        asyncio.run(provider.redeem("c", "v"))


def test_a_refresh_is_refused_only_for_invalid_grant() -> None:
    google = FakeGoogle()
    with pytest.raises(OAuthRefused):
        asyncio.run(google.provider().refresh("revoked"))
    google.down = True
    with pytest.raises(OAuthUnavailable):
        asyncio.run(google.provider().refresh("anything"))


def test_a_refresh_answers_a_new_access_token_and_a_refresh_token_only_when_rotated() -> None:
    google = FakeGoogle()
    google.refresh_tokens.add("r")
    plain = asyncio.run(google.provider().refresh("r"))
    assert plain.refresh_token is None and plain.access_token in google.access_tokens
    google.rotate = True
    rotated = asyncio.run(google.provider().refresh("r"))
    assert rotated.refresh_token in google.refresh_tokens


def test_userinfo_answers_map_to_the_checks_refusals() -> None:
    google = FakeGoogle()
    google.access_tokens.add("good")
    provider = google.provider()
    assert asyncio.run(provider.check("good")) is None
    assert asyncio.run(provider.check("bad")) == "key_refused"
    google.down = True
    assert asyncio.run(provider.check("good")) == "unreachable"


@pytest.mark.parametrize("env", [{"GOOGLE_OAUTH_CLIENT_ID": "1"}, {"GOOGLE_OAUTH_CLIENT_SECRET": "s"},
                                 {"GOOGLE_OAUTH_CLIENT_ID": "1", "GOOGLE_OAUTH_CLIENT_SECRET": "s"}])
def test_the_settings_come_as_a_pair_with_public_url(env: dict[str, str]) -> None:
    with pytest.raises(ValueError):
        from_env({"DATABASE_URL": "x", **env})
    both = {"DATABASE_URL": "x", "GOOGLE_OAUTH_CLIENT_ID": "1", "GOOGLE_OAUTH_CLIENT_SECRET": "s",
            "PUBLIC_URL": "https://ashley.test/"}
    assert from_env(both) == Settings(database_url="x", build_version="dev", google_oauth_client_id="1",
                                      google_oauth_client_secret="s", public_url="https://ashley.test")
    assert from_env({"DATABASE_URL": "x"}).google_oauth_client_id == ""


def test_userinfo_is_asked_with_the_bearer_alone() -> None:
    seen: list[httpx2.Request] = []

    def answer(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json={"email": "a@b.c"})
    provider = GoogleOAuth(App("id", "the-client-secret", REDIRECT), httpx2.AsyncClient(transport=httpx2.MockTransport(answer)))
    assert asyncio.run(provider.check("tok")) is None
    (request,) = seen
    assert request.headers["authorization"] == "Bearer tok"
    assert "the-client-secret" not in str(request.url) + str(dict(request.headers)) + request.content.decode()
