"""Blind contract tests for sign-in, written from `ashley.api.signin`'s docstring, `openapi.json`, `signin.json` and
`decisions.md` ("People sign in through OIDC") without reading the implementation. Each test names the clause it
checks. Time passes by shifting stored timestamps (`let_time_pass`), since the contract offers no clock to inject."""

import hashlib
import time
from collections.abc import Generator
from urllib.parse import parse_qs, urlsplit

import pytest
from ashley.main import create_app
from fastapi.testclient import TestClient
from joserfc.jwk import OctKey
from signin_contract_support import (FAILED, SITE, UNMAPPED, Browser, browser, count, landed, let_time_pass,
                                     map_account, set_cookies, settings, unmapped_listing)
from signin_support import CLIENT, ROTATED

DAY = 86400


@pytest.fixture
def web(db_url: str) -> Generator[Browser]:
    with browser(db_url) as b:
        yield b


@pytest.fixture
def mapped(web: Browser) -> Browser:
    map_account(web.url, web.fake.sub)
    return web


def query_of(url: str) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}


# --- the start --------------------------------------------------------------------------------------------------


def test_start_redirects_to_the_issuer_with_pkce_state_and_nonce(web: Browser) -> None:
    """GET /api/auth/signin: 302 to the provider, authorization code flow with PKCE S256 for this client."""
    r = web.start("/inbox")
    assert r.status_code == 302
    location: str = r.headers["location"]
    where = urlsplit(location)
    assert (where.scheme, where.netloc) == ("https", "auth.test")
    q = query_of(location)
    assert q["response_type"] == "code" and q["client_id"] == CLIENT.client_id
    assert q["redirect_uri"] == CLIENT.redirect_uri
    assert q["code_challenge_method"] == "S256" and len(q["code_challenge"]) == 43
    assert "openid" in q["scope"].split()
    assert len(q["state"]) >= 16 and len(q["nonce"]) >= 16


def test_start_values_are_fresh_per_sign_in(web: Browser) -> None:
    """State, nonce and PKCE challenge are random per sign-in, never reused."""
    a, b = (query_of(web.start().headers["location"]) for _ in range(2))
    for key in ("state", "nonce", "code_challenge"):
        assert a[key] != b[key], key


def test_start_keeps_this_sign_ins_state_in_a_cookie(web: Browser) -> None:
    """GET /api/auth/signin: 'with this sign-in's state in a cookie'; not readable by page scripts."""
    r = web.start()
    cookies = set_cookies(r)
    assert cookies, "no cookie set"
    assert all("httponly" in c.lower() for c in cookies), cookies


def test_start_never_answers_422_for_odd_queries(web: Browser) -> None:
    """Query parameters are read, not declared: 'no value is ever a 422'."""
    r = web.client.get("/api/auth/signin", params=[("next", "/a"), ("next", "/b"), ("junk", "\x00")])
    assert r.status_code == 302


# --- the callback: refusals -------------------------------------------------------------------------------------


def refused(web: Browser, r: object) -> None:
    assert landed(r) == FAILED
    assert not web.session_cookies()
    assert web.me().status_code == 401


def test_callback_with_wrong_state_is_refused(mapped: Browser) -> None:
    """The callback must carry the state this browser was sent with."""
    started = mapped.start()
    code, state = mapped.fake.authorize(started.headers["location"])
    refused(mapped, mapped.callback(code, state[:-1] + ("A" if state[-1] != "A" else "B")))


def test_callback_with_missing_state_is_refused(mapped: Browser) -> None:
    started = mapped.start()
    code, _ = mapped.fake.authorize(started.headers["location"])
    refused(mapped, mapped.client.get("/api/auth/callback", params={"code": code}))


def test_callback_with_missing_code_is_refused(mapped: Browser) -> None:
    started = mapped.start()
    _, state = mapped.fake.authorize(started.headers["location"])
    refused(mapped, mapped.client.get("/api/auth/callback", params={"state": state}))


def test_callback_with_provider_error_is_refused(mapped: Browser) -> None:
    """The provider's `error` on the query is a refusal, not a 500."""
    started = mapped.start()
    _, state = mapped.fake.authorize(started.headers["location"])
    refused(mapped, mapped.client.get("/api/auth/callback", params={"error": "access_denied", "state": state}))


def test_callback_without_this_browsers_state_cookie_is_refused(mapped: Browser, db_url: str) -> None:
    """'A callback from someone else's sign-in never signs this browser in': right state and code, other browser."""
    started = mapped.start()
    code, state = mapped.fake.authorize(started.headers["location"])
    with TestClient(create_app(settings(db_url)), base_url=SITE, follow_redirects=False) as stranger:
        r = stranger.get("/api/auth/callback", params={"code": code, "state": state})
        assert landed(r) == FAILED
        assert stranger.get("/api/me").status_code == 401


def test_state_is_taken_once(mapped: Browser) -> None:
    """The state is taken once: replaying a completed callback's state (cookie included) is refused."""
    started = mapped.start()
    code, state = mapped.fake.authorize(started.headers["location"])
    saved = dict(mapped.client.cookies)
    assert landed(mapped.callback(code, state)) == "/"
    mapped.client.cookies.clear()
    mapped.client.cookies.update(saved)
    second_code, _ = mapped.fake.authorize(started.headers["location"])
    refused(mapped, mapped.callback(second_code, state))


def test_state_expires_after_pending_minutes(mapped: Browser) -> None:
    """A sign-in in flight must come back within `pending_minutes` (10)."""
    started = mapped.start()
    code, state = mapped.fake.authorize(started.headers["location"])
    let_time_pass(mapped.url, "signin_pending", 11 * 60)
    refused(mapped, mapped.callback(code, state))


def test_state_in_flight_is_still_good_just_inside_pending_minutes(mapped: Browser) -> None:
    """Control for the expiry test: the same aging by 5 minutes still signs in."""
    started = mapped.start()
    code, state = mapped.fake.authorize(started.headers["location"])
    let_time_pass(mapped.url, "signin_pending", 5 * 60)
    assert landed(mapped.callback(code, state)) == "/"


def test_a_refused_code_is_refused(mapped: Browser) -> None:
    """The provider rejecting the code at the token endpoint is a refusal."""
    mapped.fake.token_status = 400
    refused(mapped, mapped.signin())


BAD_TOKENS = {
    "wrong nonce": {"claims": {"nonce": "not-the-nonce"}},
    "missing nonce": {"claims": {"nonce": None}},
    "other issuer": {"claims": {"iss": "https://evil.test/application/o/ashley/"}},
    "other audience": {"claims": {"aud": "someone-elses-client"}},
    "missing audience": {"claims": {"aud": None}},
    "expired": {"claims": {"exp": int(time.time()) - 600, "iat": int(time.time()) - 900}},
    "missing exp": {"claims": {"exp": None}},
    "missing sub": {"claims": {"sub": None}},
    "unpublished key": {"signer": ROTATED, "header": {"alg": "RS256", "kid": "unknown"}},
    "hmac token": {"signer": OctKey.import_key("k" * 48), "header": {"alg": "HS256"}},
}


@pytest.mark.parametrize("flaw", sorted(BAD_TOKENS))
def test_a_bad_id_token_is_refused(mapped: Browser, flaw: str) -> None:
    """An ID token with a wrong nonce, issuer, audience or key, or expired, is refused to `/?signin=failed`."""
    for field, value in BAD_TOKENS[flaw].items():
        setattr(mapped.fake, field, value)
    refused(mapped, mapped.signin())


def test_a_good_token_from_the_same_fake_is_accepted(mapped: Browser) -> None:
    """Control for the bad-token cases: with nothing wrong the same flow signs in."""
    assert landed(mapped.signin()) == "/"
    assert mapped.me().status_code == 200


# --- the callback: who signs in ---------------------------------------------------------------------------------


def test_unmapped_account_is_refused_and_becomes_listable(web: Browser) -> None:
    """An account no person has goes to `/?signin=unmapped`, no session, and is listed for the admin."""
    web.fake.sub, web.fake.username = "never-mapped-sub", "newcomer"
    assert landed(web.signin()) == UNMAPPED
    assert not web.session_cookies() and web.me().status_code == 401
    listing = unmapped_listing(web.url)
    assert "newcomer" in listing
    assert hashlib.sha256(b"never-mapped-sub").hexdigest()[:12] in listing


def test_unmapped_account_leaves_the_list_once_mapped(web: Browser) -> None:
    """'It then leaves this list', and the next sign-in works."""
    web.fake.sub, web.fake.username = "soon-mapped-sub", "soon"
    assert landed(web.signin()) == UNMAPPED
    map_account(web.url, "soon-mapped-sub", "Soon")
    assert landed(web.signin()) == "/"
    assert "soon" not in unmapped_listing(web.url).split()


def test_unmapped_attempts_are_bounded_by_account_not_by_attempt(web: Browser) -> None:
    """A repeated refusal of one account is one listing, not a growing table."""
    web.fake.sub = "repeat-sub"
    for _ in range(3):
        assert landed(web.signin()) == UNMAPPED
    assert count(web.url, "signin_unmapped") == 1


def test_mapped_account_gets_a_host_cookie_and_me_names_the_person(web: Browser) -> None:
    """A mapped account's session cookie is `__Host-`, Secure, HttpOnly, SameSite=Lax; /api/me returns the person."""
    pid = map_account(web.url, web.fake.sub, "Alana")
    r = web.signin("/inbox")
    assert landed(r) == "/inbox"
    host = [c for c in set_cookies(r) if c.startswith("__Host-") and "max-age=0" not in c.lower()]
    assert len(host) == 1, set_cookies(r)
    flags = [p.strip().lower() for p in host[0].split(";")]
    assert "secure" in flags and "httponly" in flags and "samesite=lax" in flags
    assert "path=/" in flags and not any(f.startswith("domain=") for f in flags)
    me = web.me()
    assert me.status_code == 200
    assert me.json()["person"]["id"] == pid and me.json()["person"]["name"] == "Alana"


def test_session_token_is_not_the_state_or_guessable(mapped: Browser) -> None:
    """Opaque random token: two sign-ins give different, long cookie values."""
    mapped.signin()
    first = next(iter(mapped.session_cookies().values()))
    mapped.signin()
    second = next(iter(mapped.session_cookies().values()))
    assert first != second and len(first) >= 32


def test_me_without_a_session_is_401_unauthorized(web: Browser) -> None:
    r = web.me()
    assert r.status_code == 401 and r.json()["code"] == "unauthorized"


def test_me_with_a_made_up_session_cookie_is_401(mapped: Browser) -> None:
    mapped.signin()
    name = next(iter(mapped.session_cookies()))
    mapped.client.cookies.set(name, "A" * 43, domain="ashley.test", path="/")
    assert mapped.me().status_code == 401


# --- next ------------------------------------------------------------------------------------------------------

OFF_SITE = ["//evil.com", "/\\evil.com", "https://evil.com", "/%2F%2Fevil.com", "http://evil.com/x", "evil.com",
            "///evil.com", "\\\\evil.com", "/\\/evil.com", "javascript:alert(1)", "//evil.com/%2e%2e", "/\t/evil.com",
            "/\r\nSet-Cookie: x=y", "/\x00", "/a\nb", "/\x1b[0m", "/" + "a" * 5000, "/ /evil.com", "/%0d%0aX: y",
            "data:text/html,x", "//\\evil.com", "/%5Cevil.com", "////evil.com"]


@pytest.mark.parametrize("nxt", OFF_SITE)
def test_next_never_leads_off_site(mapped: Browser, nxt: str) -> None:
    """`next` is a path on this site; anything else returns to `/`. Whatever Location says must stay on this site."""
    r = mapped.signin(nxt)
    location: str = r.headers["location"]
    assert r.status_code == 302
    assert all(ord(c) >= 32 and c != "\x7f" for c in location), repr(location)
    parts = urlsplit(location)
    assert parts.scheme == "" and parts.netloc == "", repr(location)
    assert location.startswith("/") and not location.startswith(("//", "/\\")), repr(location)


@pytest.mark.parametrize("nxt", ["//evil.com", "/\\evil.com", "https://evil.com", "javascript:alert(1)", "evil.com"])
def test_a_next_that_is_not_a_site_path_returns_to_root(mapped: Browser, nxt: str) -> None:
    """'anything else returns to /'."""
    assert landed(mapped.signin(nxt)) == "/"


@pytest.mark.parametrize("nxt", ["/", "/inbox", "/settings/profile?tab=memory", "/a/b/c#frag"])
def test_a_site_path_next_is_kept(mapped: Browser, nxt: str) -> None:
    """Control for the off-site cases: a real path comes back as given."""
    assert mapped.signin(nxt).headers["location"] in (nxt, nxt.split("#")[0])


def test_no_next_returns_to_root(mapped: Browser) -> None:
    assert landed(mapped.signin()) == "/"


# --- sign out ---------------------------------------------------------------------------------------------------


def test_signout_ends_the_session(mapped: Browser) -> None:
    """POST /api/auth/signout with the right Origin: 204, cookie cleared, /api/me is 401, and the old token is dead."""
    mapped.signin()
    old = dict(mapped.client.cookies)
    r = mapped.signout()
    assert r.status_code == 204
    cleared = [c for c in set_cookies(r) if c.startswith("__Host-")]
    assert cleared and ("max-age=0" in cleared[0].lower() or "expires=" in cleared[0].lower())
    assert mapped.me().status_code == 401
    mapped.client.cookies.update(old)
    assert mapped.me().status_code == 401, "the token still works after sign-out"


def test_signout_when_not_signed_in_is_still_204(web: Browser) -> None:
    assert web.signout().status_code == 204


@pytest.mark.parametrize("origin", ["https://evil.com", "http://ashley.test", "https://ashley.test.evil.com", "null",
                                    "https://ashley.test:8443", "https://sub.ashley.test"])
def test_signout_from_a_foreign_origin_is_403_and_changes_nothing(mapped: Browser, origin: str) -> None:
    """A write must come from PUBLIC_URL's origin: otherwise 403 `forbidden`, and the session lives."""
    mapped.signin()
    r = mapped.client.post("/api/auth/signout", headers={"Origin": origin})
    assert r.status_code == 403 and r.json()["code"] == "forbidden"
    assert mapped.me().status_code == 200


def test_signout_with_no_origin_from_another_site_is_403(mapped: Browser) -> None:
    """With no Origin, a Sec-Fetch-Site naming another site is refused."""
    mapped.signin()
    r = mapped.client.post("/api/auth/signout", headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403 and r.json()["code"] == "forbidden"
    assert mapped.me().status_code == 200


def test_signout_with_no_origin_and_same_origin_fetch_metadata_is_allowed(mapped: Browser) -> None:
    """The other half of the rule: no Origin but Sec-Fetch-Site same-origin is a write from this site."""
    mapped.signin()
    r = mapped.client.post("/api/auth/signout", headers={"Sec-Fetch-Site": "same-origin"})
    assert r.status_code == 204
    assert mapped.me().status_code == 401


def test_signout_with_a_form_body_is_refused(mapped: Browser) -> None:
    """'any body must be application/json': a plain form cannot sign someone out."""
    mapped.signin()
    r = mapped.client.post("/api/auth/signout", content=b"a=b",
                           headers={"Origin": SITE, "Content-Type": "application/x-www-form-urlencoded"})
    assert 400 <= r.status_code < 500
    assert mapped.me().status_code == 200


# --- lifetimes (signin.json: session_days 30, idle_days 7) ------------------------------------------------------


def test_a_session_idle_under_idle_days_is_live(mapped: Browser) -> None:
    mapped.signin()
    let_time_pass(mapped.url, "sessions", 6 * DAY)
    assert mapped.me().status_code == 200


def test_a_session_idle_past_idle_days_ends(mapped: Browser) -> None:
    mapped.signin()
    let_time_pass(mapped.url, "sessions", 8 * DAY)
    assert mapped.me().status_code == 401


def test_use_keeps_a_session_from_going_idle(mapped: Browser) -> None:
    """Six idle days, a request, six more idle days: each gap is under idle_days, so it lives (the use is recorded)."""
    mapped.signin()
    for _ in range(3):
        let_time_pass(mapped.url, "sessions", 6 * DAY)
        assert mapped.me().status_code == 200


def test_a_session_ends_at_session_days_however_much_it_is_used(mapped: Browser) -> None:
    """Used every six days it is never idle, yet 'lasts at most session_days' (30) from sign-in."""
    mapped.signin()
    for _ in range(4):
        let_time_pass(mapped.url, "sessions", 6 * DAY)
        assert mapped.me().status_code == 200
    let_time_pass(mapped.url, "sessions", 6 * DAY)
    assert mapped.me().status_code == 401


def test_an_expired_session_is_not_revived_by_the_next_request(mapped: Browser) -> None:
    mapped.signin()
    let_time_pass(mapped.url, "sessions", 8 * DAY)
    assert mapped.me().status_code == 401
    assert mapped.me().status_code == 401


# --- unconfigured -----------------------------------------------------------------------------------------------


def test_oidc_unset_is_503_and_the_app_still_serves(db_url: str) -> None:
    """Unconfigured, sign-in answers 503 `unavailable` and the rest of the app runs."""
    with TestClient(create_app(settings(db_url, oidc=False)), base_url=SITE, follow_redirects=False) as client:
        r = client.get("/api/auth/signin")
        assert r.status_code == 503 and r.json()["code"] == "unavailable"
        r = client.get("/api/auth/callback", params={"code": "c", "state": "s"})
        assert (r.status_code, r.headers.get("location")) in ((503, None), (302, FAILED)), r.status_code
        assert client.get("/api/health").status_code == 200
        assert client.get("/api/me").status_code in (401, 503)
